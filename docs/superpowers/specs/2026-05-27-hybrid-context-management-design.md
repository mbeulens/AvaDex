# Hybrid Context Management (dedup + proactive compaction)

**Date:** 2026-05-27
**Status:** Approved design, pending implementation plan

## Problem

AvaDex's agent currently manages context with a single crude mechanism: `context.py:prune()`
drops the oldest messages (FIFO) until the conversation fits `max_context_tokens`, keeping
`tool_use`/`tool_result` pairs together. A second fallback in `agent_loop.py` drops the four
oldest messages on a hard `ContextOverflow`, then gives up and tells the user to `/clear`.

This is lossy and blunt:

- It throws away the *beginning* of the conversation (often the user's original goal) first.
- It never reclaims space from obviously-redundant content (re-reads of the same file, denied
  tool calls, huge stale tool outputs).
- `prune` is only called **once** per user turn, so a long agentic turn (up to 50 iterations)
  grows unbounded inside the iteration loop until it overflows.

## Goal

Let an AvaDex session run as long as possible before losing useful context, by:

1. **Dedup pass** (cheap, deterministic, no LLM call) — reclaim space from redundant content.
2. **Compaction pass** (proactive, one LLM call) — summarize old turns when usage crosses a
   high-water mark, preserving the information the agent still needs.
3. Keeping the existing FIFO `prune` as a last-resort backstop.

This is the "hybrid" approach: dedup first (free), summarize second (proactive), FIFO last.

## Non-goals

- No per-message manual deletion UI.
- No separate/cheaper summarization model — compaction reuses the session model.
- No change to the existing `ContextOverflow` exception handler beyond keeping it as a backstop.

## Architecture (Approach A: functional orchestrator + summarizer callback)

All new logic lives in `context.py` as pure functions, consistent with the existing
`prune`/`estimate_tokens` style. The one impure dependency — the LLM call needed for
summarization — is injected as a **callback**, so `context.py` never imports the Ava client and
stays fully unit-testable.

### Entry point

```python
fit_context(
    messages: list[dict],
    *,
    max_tokens: int,
    threshold: float,            # high-water fraction, e.g. 0.8
    summarizer,                  # Callable[[list[dict]], str | None] | None
    large_output_tokens: int,
    keep_recent: int,
) -> list[dict]
```

Logic:

1. `total = estimate_tokens(messages)`. If `total <= threshold * max_tokens` → return
   `messages` unchanged (under the high-water mark; do nothing).
2. `messages = dedup(messages, large_output_tokens=..., keep_recent=...)`; recompute `total`.
3. If `total > threshold * max_tokens` **and** `summarizer is not None`:
   `messages = compact(messages, summarizer, keep_recent=...)`; recompute `total`.
4. If `total > max_tokens` (hard ceiling) → `messages = prune(messages, max_tokens)`
   (existing FIFO backstop).
5. Return `messages`.

### `dedup(messages, *, large_output_tokens, keep_recent)`

Deterministic, no LLM. Never modifies the last `keep_recent` messages. Three operations:

- **Superseded `read_file`s** — group `read_file` `tool_use` blocks by their `path` input arg.
  For every read except the most recent of each path, replace its matching `tool_result`
  *body* with the stub `[superseded by a later read of <path>]`. The bulky content is the
  result body; the small `tool_use` call stays, so structure/pairing remain trivially valid.
- **Denied tool calls** — remove the `tool_use` block and its `denied by user` `tool_result`
  as a pair, reusing the existing pairing helpers (`_tool_use_ids` / `_tool_result_ids` /
  pair index) in `context.py`. If removing the `tool_use` leaves an assistant message with no
  remaining content blocks, drop that message too.
- **Large outputs** — any `tool_result` older than the `keep_recent` window whose token
  estimate exceeds `large_output_tokens` has its body replaced with
  `[output truncated to save context: ~N tokens]`. **Errored results (`is_error == True`) are
  left intact** so the agent can still learn from past failures.

### `compact(messages, summarizer, *, keep_recent)`

One LLM call, via the injected `summarizer` callback.

- Keep the last `keep_recent` messages verbatim; everything older is the "old segment."
- Adjust the cut boundary so the kept segment never *starts* with an orphaned `tool_result`
  (whose `tool_use` would be stranded in the old segment): while the message at the cut index
  is a `tool_result`-bearing user message, move the cut earlier by one. If the cut reaches 0,
  there is nothing to compact → return unchanged.
- If `len(messages) <= keep_recent` → return unchanged.
- Call `summarizer(old_segment)`:
  - On success → replace the entire old segment with a single message:
    `{"role": "user", "content": "[Earlier conversation summary]\n<text>"}`, followed by the
    kept recent messages.
  - On `None` (LLM call failed) → return `messages` unchanged, so the FIFO backstop can handle
    it. This is the contract that keeps `context.py` network-free.

The summarization prompt instructs the model to preserve all four categories:

1. **User goals & requests** — the original task(s) the user asked for.
2. **Key facts & data** — concrete values discovered: IDs, API results, filenames, numbers.
3. **Decisions & rationale** — choices made and why, so settled questions aren't relitigated.
4. **Pending next steps** — outstanding TODOs / the plan for what comes next.

## Wiring (`agent_loop.py`)

- Replace the single `prune` call at `run_turn` (currently line 78) with `fit_context(...)`.
- **Also call `fit_context` at the top of each iteration** of the tool-use loop, before each
  `client.messages` call, so proactive compaction can fire mid-turn as tool results
  accumulate. This is what makes "proactive at threshold" effective during long agentic runs.
- Add `AgentLoop._summarize(old) -> str | None` used as the `summarizer` callback:

  ```python
  def _summarize(self, old):
      old = prune(old, self.max_context_tokens)  # bound the summary call's own input
      try:
          resp = self.client.messages(
              system=COMPACTION_SYSTEM_PROMPT,
              messages=old + [{"role": "user", "content": COMPACTION_INSTRUCTION}],
              tools=[],
              max_tokens=self.max_response_tokens,
              model=self.model,
          )
      except (AvaError, ContextOverflow, TokenExpired):
          return None
      return "".join(b.text for b in resp.content if isinstance(b, TextBlock))
  ```

- `COMPACTION_SYSTEM_PROMPT` and `COMPACTION_INSTRUCTION` are module-level constants in
  `agent_loop.py` (they encode the four preserve categories above). The summary response is
  capped at `self.max_response_tokens`.
- The existing `ContextOverflow` handler (currently lines 92–106) stays unchanged as the
  ultimate backstop.

## Config (`config.py`) — three new optional fields

| Field | Default | Meaning |
|---|---|---|
| `context_compaction_threshold` | `0.8` | High-water fraction of `max_context_tokens` that engages dedup + compaction |
| `context_large_output_tokens` | `1000` | Tool results larger than this (outside the recent window) are stubbed by dedup |
| `context_keep_recent` | `6` | Messages kept verbatim — protected from dedup stubbing *and* the compaction cut |

- Added to the `Config` dataclass with defaults.
- Read in `load_config` via `data.get(...)`, matching the existing pattern (optional in TOML).
- Threaded through `AgentLoop.__init__` and the construction site in `cli.py`, exactly as
  `max_iterations` was wired.

## Error handling (layered, never crashes a turn)

1. Summarizer LLM call fails → returns `None` → `compact` no-ops →
2. FIFO `prune` backstop trims to the hard ceiling →
3. Existing `ContextOverflow` handler in `agent_loop.py` is the final safety net.

`context.py` imports nothing from the client/network layer.

## Testing

New tests extend `tests/`. `context.py` tests use a fake summarizer lambda
(`lambda old: "SUMMARY"`) — no client mocking required.

**dedup**
- Superseded reads: latest read of a path kept, earlier ones stubbed.
- Denied pairs removed; assistant message dropped if it becomes empty.
- Large old outputs stubbed; errored results preserved untouched.
- Recent `keep_recent` window never modified.
- `tool_use`/`tool_result` pairing invariant holds after dedup.

**compact**
- Cut boundary never leaves an orphaned `tool_result` at the start of the kept segment.
- Old segment replaced by exactly one `[Earlier conversation summary]` message.
- `summarizer` returns `None` → messages unchanged.
- History `<= keep_recent` → unchanged.

**fit_context**
- Under threshold → no-op, and `summarizer` is never called.
- Dedup alone brings it under threshold → `summarizer` not called.
- Dedup insufficient → `summarizer` called.
- Over hard ceiling after compaction → `prune` backstop fires.

**agent_loop**
- `fit_context` invoked at the top of each iteration.
- Summarizer raising an exception → `_summarize` returns `None` → turn still completes.

## Out-of-scope follow-ups (not in this work)
- A configurable/cheaper summarization model.
- Reference-graph analysis for "unreferenced" outputs (current heuristic = large + old).
