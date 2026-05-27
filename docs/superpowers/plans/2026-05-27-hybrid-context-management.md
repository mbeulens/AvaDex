# Hybrid Context Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let AvaDex sessions run far longer before losing context, by reclaiming space from redundant messages (dedup) and proactively summarizing old turns (compaction) before the budget is exhausted.

**Architecture:** All context logic stays in `avadex/context.py` as pure functions. A single `fit_context` orchestrator runs dedup (deterministic), then compaction (one LLM call via an injected `summarizer` callback), then the existing FIFO `prune` as a backstop. `agent_loop.py` provides the callback (which calls the Ava client and swallows errors into `None`) and calls `fit_context` at the top of every iteration. Three new config fields tune the behavior.

**Tech Stack:** Python 3.12, pytest, `tomllib`/`tomli_w` for config. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-05-27-hybrid-context-management-design.md`

---

## File Structure

- `avadex/context.py` (modify) — add `import copy`; add private helpers `_protected_start`, `_result_index`, `_starts_with_tool_result`, `_stub_superseded_reads`, `_drop_denied_calls`, `_stub_large_outputs`; add public `dedup`, `compact`, `fit_context`. Existing `estimate_tokens` and `prune` are reused unchanged.
- `avadex/config.py` (modify) — add three fields to `Config` and read them in `load_config`.
- `avadex/agent_loop.py` (modify) — add compaction prompt constants, `_summarize` and `_fit` methods, three constructor params; call `_fit()` at the top of the iteration loop instead of the one-time `prune`.
- `avadex/cli.py` (modify) — pass the three new config fields into `AgentLoop(...)`.
- `tests/unit/test_context.py` (modify) — tests for all new context functions.
- `tests/unit/test_config.py` (modify or create) — tests for the new config fields.
- `tests/unit/test_agent_loop_compaction.py` (create) — integration tests for `_summarize` and per-iteration `_fit`.

Message shapes (already used throughout the codebase):
- User text: `{"role": "user", "content": "some string"}`
- Assistant: `{"role": "assistant", "content": [ {"type": "text", "text": ...}, {"type": "tool_use", "id": ..., "name": ..., "input": {...}} ]}`
- Tool results: `{"role": "user", "content": [ {"type": "tool_result", "tool_use_id": ..., "content": "...", "is_error": bool} ]}`

---

## Task 1: Shared helpers + superseded-read stubbing

**Files:**
- Modify: `avadex/context.py` (top of file and new functions)
- Test: `tests/unit/test_context.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_context.py`:

```python
def test_stub_superseded_reads_keeps_only_latest():
    from avadex.context import _stub_superseded_reads
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "r1", "name": "read_file", "input": {"path": "/a.py"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "r1", "content": "OLD CONTENT", "is_error": False}]},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "r2", "name": "read_file", "input": {"path": "/a.py"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "r2", "content": "NEW CONTENT", "is_error": False}]},
    ]
    out = _stub_superseded_reads(messages, keep_recent=0)
    assert out[1]["content"][0]["content"] == "[superseded by a later read of /a.py]"
    assert out[3]["content"][0]["content"] == "NEW CONTENT"


def test_stub_superseded_reads_respects_recent_window():
    from avadex.context import _stub_superseded_reads
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "r1", "name": "read_file", "input": {"path": "/a.py"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "r1", "content": "OLD CONTENT", "is_error": False}]},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "r2", "name": "read_file", "input": {"path": "/a.py"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "r2", "content": "NEW CONTENT", "is_error": False}]},
    ]
    # keep_recent=4 protects everything → no stubbing
    out = _stub_superseded_reads(messages, keep_recent=4)
    assert out[1]["content"][0]["content"] == "OLD CONTENT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_context.py::test_stub_superseded_reads_keeps_only_latest -v`
Expected: FAIL with `ImportError: cannot import name '_stub_superseded_reads'`

- [ ] **Step 3: Write minimal implementation**

At the top of `avadex/context.py`, change the imports block to add `copy`:

```python
from __future__ import annotations

import copy
import json
```

Then add these functions (after `estimate_tokens`, before `prune`):

```python
def _protected_start(n: int, keep_recent: int) -> int:
    """Index at/after which messages are protected from modification."""
    return max(0, n - keep_recent)


def _result_index(messages: list[dict], tool_use_id: str):
    """Return (message_index, result_block) for a tool_use_id, or (None, None)."""
    for i, m in enumerate(messages):
        c = m.get("content")
        if isinstance(c, list):
            for b in c:
                if b.get("type") == "tool_result" and b.get("tool_use_id") == tool_use_id:
                    return i, b
    return None, None


def _stub_superseded_reads(messages: list[dict], keep_recent: int) -> list[dict]:
    """Replace the result body of every read_file except the latest per path."""
    protected = _protected_start(len(messages), keep_recent)
    reads: list[tuple[int, str, str]] = []  # (msg_index, tool_use_id, path)
    for i, m in enumerate(messages):
        if m.get("role") != "assistant":
            continue
        c = m.get("content")
        if not isinstance(c, list):
            continue
        for b in c:
            if b.get("type") == "tool_use" and b.get("name") == "read_file":
                path = (b.get("input") or {}).get("path")
                if path and b.get("id"):
                    reads.append((i, b["id"], path))
    latest: dict[str, str] = {}
    for _, tid, path in reads:
        latest[path] = tid  # later entries win → highest-index read per path
    for _, tid, path in reads:
        if tid == latest[path]:
            continue
        ri, block = _result_index(messages, tid)
        if ri is None or ri >= protected:
            continue
        block["content"] = f"[superseded by a later read of {path}]"
    return messages
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_context.py::test_stub_superseded_reads_keeps_only_latest tests/unit/test_context.py::test_stub_superseded_reads_respects_recent_window -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add avadex/context.py tests/unit/test_context.py
git commit -m "Add superseded-read stubbing helper to context.py"
```

---

## Task 2: Denied-tool-call removal

**Files:**
- Modify: `avadex/context.py`
- Test: `tests/unit/test_context.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_context.py`:

```python
def test_drop_denied_calls_removes_pair_and_empty_message():
    from avadex.context import _drop_denied_calls
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "d1", "name": "bash", "input": {"cmd": "rm -rf /"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "d1", "content": "denied by user", "is_error": True}]},
        {"role": "assistant", "content": "ok, moving on"},
    ]
    out = _drop_denied_calls(messages, keep_recent=0)
    assert len(out) == 1
    assert out[0]["content"] == "ok, moving on"


def test_drop_denied_calls_keeps_mixed_blocks():
    from avadex.context import _drop_denied_calls
    messages = [
        {"role": "assistant", "content": [
            {"type": "text", "text": "let me try two things"},
            {"type": "tool_use", "id": "d1", "name": "bash", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "d1", "content": "denied by user", "is_error": True}]},
    ]
    out = _drop_denied_calls(messages, keep_recent=0)
    # The assistant message keeps its text block; the tool_use and its result are gone.
    assert out[0]["content"] == [{"type": "text", "text": "let me try two things"}]
    assert len(out) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_context.py::test_drop_denied_calls_removes_pair_and_empty_message -v`
Expected: FAIL with `ImportError: cannot import name '_drop_denied_calls'`

- [ ] **Step 3: Write minimal implementation**

Add to `avadex/context.py` (after `_stub_superseded_reads`):

```python
def _drop_denied_calls(messages: list[dict], keep_recent: int) -> list[dict]:
    """Remove tool_use blocks and their 'denied by user' results as pairs."""
    protected = _protected_start(len(messages), keep_recent)
    denied_ids: set[str] = set()
    for i, m in enumerate(messages):
        if i >= protected:
            continue
        c = m.get("content")
        if isinstance(c, list):
            for b in c:
                if (b.get("type") == "tool_result"
                        and b.get("is_error")
                        and b.get("content") == "denied by user"
                        and b.get("tool_use_id")):
                    denied_ids.add(b["tool_use_id"])
    if not denied_ids:
        return messages
    out: list[dict] = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            new_blocks = [
                b for b in c
                if not (
                    (b.get("type") == "tool_use" and b.get("id") in denied_ids)
                    or (b.get("type") == "tool_result" and b.get("tool_use_id") in denied_ids)
                )
            ]
            if not new_blocks:
                continue  # drop a message that became empty
            m = {**m, "content": new_blocks}
        out.append(m)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_context.py::test_drop_denied_calls_removes_pair_and_empty_message tests/unit/test_context.py::test_drop_denied_calls_keeps_mixed_blocks -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add avadex/context.py tests/unit/test_context.py
git commit -m "Add denied-tool-call removal helper to context.py"
```

---

## Task 3: Large-output stubbing (errors preserved)

**Files:**
- Modify: `avadex/context.py`
- Test: `tests/unit/test_context.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_context.py`:

```python
def test_stub_large_outputs_truncates_big_non_error():
    from avadex.context import _stub_large_outputs
    big = "x" * 8000  # ~2400 token estimate
    messages = [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": big, "is_error": False}]},
        {"role": "assistant", "content": "next"},
    ]
    out = _stub_large_outputs(messages, large_output_tokens=1000, keep_recent=0)
    assert out[0]["content"][0]["content"].startswith("[output truncated to save context:")


def test_stub_large_outputs_preserves_errors():
    from avadex.context import _stub_large_outputs
    big_err = "e" * 8000
    messages = [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": big_err, "is_error": True}]},
        {"role": "assistant", "content": "next"},
    ]
    out = _stub_large_outputs(messages, large_output_tokens=1000, keep_recent=0)
    assert out[0]["content"][0]["content"] == big_err


def test_stub_large_outputs_leaves_small_outputs():
    from avadex.context import _stub_large_outputs
    messages = [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "tiny", "is_error": False}]},
        {"role": "assistant", "content": "next"},
    ]
    out = _stub_large_outputs(messages, large_output_tokens=1000, keep_recent=0)
    assert out[0]["content"][0]["content"] == "tiny"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_context.py::test_stub_large_outputs_truncates_big_non_error -v`
Expected: FAIL with `ImportError: cannot import name '_stub_large_outputs'`

- [ ] **Step 3: Write minimal implementation**

Add to `avadex/context.py` (after `_drop_denied_calls`):

```python
def _stub_large_outputs(messages: list[dict], large_output_tokens: int,
                        keep_recent: int) -> list[dict]:
    """Stub the body of large, non-error tool_results older than the recent window."""
    protected = _protected_start(len(messages), keep_recent)
    for i, m in enumerate(messages):
        if i >= protected:
            continue
        c = m.get("content")
        if not isinstance(c, list):
            continue
        for b in c:
            if b.get("type") != "tool_result" or b.get("is_error"):
                continue
            content = b.get("content")
            if isinstance(content, str) and estimate_tokens(content) > large_output_tokens:
                approx = estimate_tokens(content)
                b["content"] = f"[output truncated to save context: ~{approx} tokens]"
    return messages
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_context.py -k stub_large_outputs -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add avadex/context.py tests/unit/test_context.py
git commit -m "Add large-output stubbing helper to context.py"
```

---

## Task 4: `dedup` coordinator (deep-copies input)

**Files:**
- Modify: `avadex/context.py`
- Test: `tests/unit/test_context.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_context.py`:

```python
def test_dedup_applies_all_passes():
    from avadex.context import dedup
    big = "x" * 8000
    messages = [
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "r1", "name": "read_file", "input": {"path": "/a.py"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "r1", "content": big, "is_error": False}]},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "r2", "name": "read_file", "input": {"path": "/a.py"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "r2", "content": "NEW", "is_error": False}]},
        {"role": "user", "content": "recent"},
        {"role": "user", "content": "recent2"},
    ]
    out = dedup(messages, large_output_tokens=1000, keep_recent=2)
    # r1 is a superseded read AND large → its body must be stubbed
    assert out[1]["content"][0]["content"].startswith("[superseded by a later read")


def test_dedup_does_not_mutate_input():
    from avadex.context import dedup
    big = "x" * 8000
    messages = [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": big, "is_error": False}]},
        {"role": "assistant", "content": "a"},
        {"role": "assistant", "content": "b"},
    ]
    dedup(messages, large_output_tokens=1000, keep_recent=0)
    assert messages[0]["content"][0]["content"] == big  # original untouched
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_context.py::test_dedup_applies_all_passes -v`
Expected: FAIL with `ImportError: cannot import name 'dedup'`

- [ ] **Step 3: Write minimal implementation**

Add to `avadex/context.py` (after `_stub_large_outputs`):

```python
def dedup(messages: list[dict], *, large_output_tokens: int, keep_recent: int) -> list[dict]:
    """Reclaim context space from redundant content without an LLM call.

    Operates on a deep copy so the caller's messages are never mutated.
    """
    msgs = copy.deepcopy(messages)
    msgs = _stub_superseded_reads(msgs, keep_recent)
    msgs = _drop_denied_calls(msgs, keep_recent)
    msgs = _stub_large_outputs(msgs, large_output_tokens, keep_recent)
    return msgs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_context.py::test_dedup_applies_all_passes tests/unit/test_context.py::test_dedup_does_not_mutate_input -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add avadex/context.py tests/unit/test_context.py
git commit -m "Add dedup coordinator to context.py"
```

---

## Task 5: `compact` with boundary safety

**Files:**
- Modify: `avadex/context.py`
- Test: `tests/unit/test_context.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_context.py`:

```python
def test_compact_replaces_old_with_summary():
    from avadex.context import compact
    messages = [
        {"role": "user", "content": "goal"},
        {"role": "assistant", "content": "work1"},
        {"role": "user", "content": "more"},
        {"role": "assistant", "content": "work2"},
        {"role": "user", "content": "recent1"},
        {"role": "assistant", "content": "recent2"},
    ]
    out = compact(messages, lambda old: "SUMMARY", keep_recent=2)
    assert out[0] == {"role": "user", "content": "[Earlier conversation summary]\nSUMMARY"}
    assert out[1:] == messages[-2:]


def test_compact_none_summary_is_noop():
    from avadex.context import compact
    messages = [{"role": "user", "content": f"m{i}"} for i in range(6)]
    out = compact(messages, lambda old: None, keep_recent=2)
    assert out == messages


def test_compact_small_history_is_noop():
    from avadex.context import compact
    messages = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    out = compact(messages, lambda old: "S", keep_recent=6)
    assert out == messages


def test_compact_boundary_avoids_orphan_tool_result():
    from avadex.context import compact
    messages = [
        {"role": "user", "content": "goal"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "x1", "name": "bash", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "x1", "content": "ok", "is_error": False}]},
        {"role": "assistant", "content": "done"},
    ]
    out = compact(messages, lambda old: "S", keep_recent=2)
    kept = out[1:]  # out[0] is the summary
    has_use = any(isinstance(m["content"], list)
                  and any(b.get("type") == "tool_use" for b in m["content"]) for m in kept)
    has_result = any(isinstance(m["content"], list)
                     and any(b.get("type") == "tool_result" for b in m["content"]) for m in kept)
    assert has_use and has_result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_context.py::test_compact_replaces_old_with_summary -v`
Expected: FAIL with `ImportError: cannot import name 'compact'`

- [ ] **Step 3: Write minimal implementation**

Add to `avadex/context.py` (after `dedup`):

```python
def _starts_with_tool_result(message: dict) -> bool:
    c = message.get("content")
    return isinstance(c, list) and any(b.get("type") == "tool_result" for b in c)


def compact(messages: list[dict], summarizer, *, keep_recent: int) -> list[dict]:
    """Replace old turns with a single summary message produced by `summarizer`.

    `summarizer(old_messages) -> str | None`. Returning None leaves messages
    unchanged so a failed summary never crashes the turn.
    """
    n = len(messages)
    if n <= keep_recent:
        return messages
    cut = n - keep_recent
    # Move the cut earlier so the kept segment never begins with an orphaned
    # tool_result (whose tool_use would be stranded in the old segment).
    while cut > 0 and _starts_with_tool_result(messages[cut]):
        cut -= 1
    if cut <= 0:
        return messages
    old, recent = messages[:cut], messages[cut:]
    summary = summarizer(old)
    if summary is None:
        return messages
    summary_msg = {"role": "user", "content": f"[Earlier conversation summary]\n{summary}"}
    return [summary_msg] + recent
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_context.py -k compact -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add avadex/context.py tests/unit/test_context.py
git commit -m "Add compact (summarization) to context.py"
```

---

## Task 6: `fit_context` orchestrator

**Files:**
- Modify: `avadex/context.py`
- Test: `tests/unit/test_context.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_context.py`:

```python
def test_fit_context_under_threshold_is_noop():
    from avadex.context import fit_context
    called = []
    messages = [{"role": "user", "content": "hi"}]
    out = fit_context(messages, max_tokens=1000, threshold=0.8,
                      summarizer=lambda old: called.append(1) or "S",
                      large_output_tokens=1000, keep_recent=6)
    assert out == messages
    assert called == []  # summarizer never called


def test_fit_context_dedup_alone_avoids_summary():
    from avadex.context import fit_context
    called = []
    big = "x" * 8000  # ~2400 tokens, will be stubbed by dedup
    messages = [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": big, "is_error": False}]},
        {"role": "user", "content": "small recent"},
        {"role": "user", "content": "small recent 2"},
    ]
    out = fit_context(messages, max_tokens=1000, threshold=0.8,
                      summarizer=lambda old: called.append(1) or "S",
                      large_output_tokens=500, keep_recent=2)
    assert called == []  # dedup brought it under threshold; no LLM call


def test_fit_context_summarizes_when_dedup_insufficient():
    from avadex.context import fit_context
    called = []
    messages = [{"role": "user", "content": "x" * 4000} for _ in range(6)]  # ~1200 tok each
    out = fit_context(messages, max_tokens=3000, threshold=0.8,
                      summarizer=lambda old: called.append(len(old)) or "S",
                      large_output_tokens=500, keep_recent=2)
    assert called  # summarizer invoked
    assert out[0]["content"] == "[Earlier conversation summary]\nS"


def test_fit_context_prune_backstop_when_still_over():
    from avadex.context import fit_context
    # Summarizer returns None → compaction no-ops → prune must trim to ceiling.
    messages = [{"role": "user", "content": "x" * 4000} for _ in range(6)]
    out = fit_context(messages, max_tokens=2000, threshold=0.8,
                      summarizer=lambda old: None,
                      large_output_tokens=500, keep_recent=2)
    total = sum(estimate_tokens(m) for m in out)
    assert total <= 2000 or len(out) == 1
```

(`estimate_tokens` is already imported at the top of `test_context.py`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_context.py::test_fit_context_under_threshold_is_noop -v`
Expected: FAIL with `ImportError: cannot import name 'fit_context'`

- [ ] **Step 3: Write minimal implementation**

Add to `avadex/context.py` (after `compact`):

```python
def fit_context(messages: list[dict], *, max_tokens: int, threshold: float,
                summarizer, large_output_tokens: int, keep_recent: int) -> list[dict]:
    """Make `messages` fit the budget: dedup, then proactive compaction, then FIFO.

    - threshold: high-water fraction of max_tokens that engages management.
    - summarizer: Callable[[list[dict]], str | None] | None used by compaction.
    """
    high_water = threshold * max_tokens
    if sum(estimate_tokens(m) for m in messages) <= high_water:
        return messages
    messages = dedup(messages, large_output_tokens=large_output_tokens,
                     keep_recent=keep_recent)
    if sum(estimate_tokens(m) for m in messages) > high_water and summarizer is not None:
        messages = compact(messages, summarizer, keep_recent=keep_recent)
    if sum(estimate_tokens(m) for m in messages) > max_tokens:
        messages = prune(messages, max_tokens)
    return messages
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_context.py -k fit_context -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add avadex/context.py tests/unit/test_context.py
git commit -m "Add fit_context orchestrator to context.py"
```

---

## Task 7: Config fields

**Files:**
- Modify: `avadex/config.py:29-38` (Config dataclass) and `avadex/config.py:47-57` (load_config)
- Test: `tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_config.py` (create the file with this content if it does not exist):

```python
def test_config_context_management_defaults(tmp_path):
    from avadex.config import load_config
    p = tmp_path / "config.toml"
    p.write_text('ava_url = "http://x"\nava_token = "t"\n')
    cfg = load_config(p)
    assert cfg.context_compaction_threshold == 0.8
    assert cfg.context_large_output_tokens == 1000
    assert cfg.context_keep_recent == 6


def test_config_context_management_overrides(tmp_path):
    from avadex.config import load_config
    p = tmp_path / "config.toml"
    p.write_text(
        'ava_url = "http://x"\n'
        'ava_token = "t"\n'
        'context_compaction_threshold = 0.5\n'
        'context_large_output_tokens = 200\n'
        'context_keep_recent = 3\n'
    )
    cfg = load_config(p)
    assert cfg.context_compaction_threshold == 0.5
    assert cfg.context_large_output_tokens == 200
    assert cfg.context_keep_recent == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_config.py::test_config_context_management_defaults -v`
Expected: FAIL with `AttributeError: 'Config' object has no attribute 'context_compaction_threshold'`

- [ ] **Step 3: Write minimal implementation**

In `avadex/config.py`, add three fields to the `Config` dataclass (after `max_iterations`):

```python
    max_iterations: int = 50          # max tool-use round-trips per user turn
    context_compaction_threshold: float = 0.8  # high-water fraction that engages dedup+compaction
    context_large_output_tokens: int = 1000    # tool results bigger than this get stubbed by dedup
    context_keep_recent: int = 6               # messages kept verbatim (protected from dedup/compaction)
    system_prompt_path: str = ""
```

In `load_config`, add the three `data.get` lines (after `max_iterations=...`):

```python
            max_iterations=data.get("max_iterations", 50),
            context_compaction_threshold=data.get("context_compaction_threshold", 0.8),
            context_large_output_tokens=data.get("context_large_output_tokens", 1000),
            context_keep_recent=data.get("context_keep_recent", 6),
            system_prompt_path=data.get("system_prompt_path", ""),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_config.py -k context_management -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add avadex/config.py tests/unit/test_config.py
git commit -m "Add context-management config fields"
```

---

## Task 8: Wire compaction into AgentLoop + CLI

**Files:**
- Modify: `avadex/agent_loop.py` (imports, module constants, `__init__`, `run_turn`, new `_summarize`/`_fit`)
- Modify: `avadex/cli.py:174-182` (pass new config fields)
- Test: `tests/unit/test_agent_loop_compaction.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_agent_loop_compaction.py`:

```python
from avadex.renderer import RecordingRenderer
from avadex.tools.registry import ToolRegistry
from avadex.permissions import PermissionManager
from avadex.agent_loop import AgentLoop, COMPACTION_INSTRUCTION
from avadex.ava_client import AvaError
from avadex.types import AvaResponse, TextBlock


class SummClient:
    def messages(self, system, messages, tools, max_tokens=2048, model="gemma4"):
        return AvaResponse(content=[TextBlock(text="THE SUMMARY")],
                           model="gemma4", stop_reason="end_turn", usage={})


class BoomClient:
    def messages(self, system, messages, tools, max_tokens=2048, model="gemma4"):
        raise AvaError("boom")


def _loop(client, tmp_path, **kw):
    return AgentLoop(
        client=client, registry=ToolRegistry(),
        permissions=PermissionManager(tmp_path / "allow.toml"),
        system_prompt="", **kw,
    )


def test_summarize_extracts_text(tmp_path):
    loop = _loop(SummClient(), tmp_path, max_context_tokens=1000)
    assert loop._summarize([{"role": "user", "content": "x"}]) == "THE SUMMARY"


def test_summarize_returns_none_on_error(tmp_path):
    loop = _loop(BoomClient(), tmp_path, max_context_tokens=1000)
    assert loop._summarize([{"role": "user", "content": "x"}]) is None


def test_run_turn_compacts_long_history(tmp_path):
    class Client:
        def __init__(self):
            self.saw_summary_call = False
        def messages(self, system, messages, tools, max_tokens=2048, model="gemma4"):
            if messages and messages[-1].get("content") == COMPACTION_INSTRUCTION:
                self.saw_summary_call = True
                return AvaResponse(content=[TextBlock(text="SUMMARY")],
                                   model="gemma4", stop_reason="end_turn", usage={})
            return AvaResponse(content=[TextBlock(text="ok")],
                               model="gemma4", stop_reason="end_turn", usage={})

    client = Client()
    loop = _loop(client, tmp_path, max_context_tokens=2000,
                 compaction_threshold=0.5, keep_recent=2)
    loop.messages = [{"role": "user", "content": "x" * 4000} for _ in range(6)]
    loop.run_turn("new question", RecordingRenderer())
    assert client.saw_summary_call
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_agent_loop_compaction.py -v`
Expected: FAIL with `ImportError: cannot import name 'COMPACTION_INSTRUCTION'`

- [ ] **Step 3: Write minimal implementation**

In `avadex/agent_loop.py`:

(a) Change the context import (line 9) to include `fit_context`:

```python
from avadex.context import prune, fit_context
```

(b) Add module-level constants after `MAX_ITERATIONS = 50`:

```python
MAX_ITERATIONS = 50

COMPACTION_SYSTEM_PROMPT = (
    "You are compacting an AI agent's conversation history to save context. "
    "Write a concise summary of the conversation so far that faithfully preserves: "
    "(1) the user's goals and original requests; "
    "(2) key facts and data discovered — IDs, API results, filenames, numbers; "
    "(3) decisions made and the reasoning behind them; "
    "(4) pending next steps and outstanding TODOs. "
    "Be specific. Do not invent information. Output only the summary."
)
COMPACTION_INSTRUCTION = (
    "Summarize the conversation above per your instructions, preserving goals, "
    "key facts/data, decisions, and pending next steps."
)
```

(c) Add three params to `AgentLoop.__init__` (after `max_iterations`) and store them:

```python
        max_iterations: int = MAX_ITERATIONS,
        compaction_threshold: float = 0.8,
        large_output_tokens: int = 1000,
        keep_recent: int = 6,
    ):
        self.client = client
        self.registry = registry
        self.permissions = permissions
        self.system_prompt = system_prompt
        self.max_context_tokens = max_context_tokens
        self.max_response_tokens = max_response_tokens
        self.model = model
        self.max_iterations = max_iterations
        self.compaction_threshold = compaction_threshold
        self.large_output_tokens = large_output_tokens
        self.keep_recent = keep_recent
        self.messages: list[dict] = []
        self.prompt_user = prompt_user or (lambda tool, args: ("deny", None))
```

(d) Add `_fit` and `_summarize` methods (place after `clear`):

```python
    def _fit(self) -> list[dict]:
        return fit_context(
            self.messages,
            max_tokens=self.max_context_tokens,
            threshold=self.compaction_threshold,
            summarizer=self._summarize,
            large_output_tokens=self.large_output_tokens,
            keep_recent=self.keep_recent,
        )

    def _summarize(self, old: list[dict]) -> "str | None":
        bounded = prune(old, self.max_context_tokens)
        try:
            with Spinner():
                resp = self.client.messages(
                    system=COMPACTION_SYSTEM_PROMPT,
                    messages=bounded + [{"role": "user", "content": COMPACTION_INSTRUCTION}],
                    tools=[],
                    max_tokens=self.max_response_tokens,
                    model=self.model,
                )
        except (AvaError, ContextOverflow, TokenExpired):
            return None
        text = "".join(b.text for b in resp.content if isinstance(b, TextBlock) and b.text)
        return text or None
```

(e) In `run_turn`, replace the current lines 77-78:

```python
        self.messages.append({"role": "user", "content": user_text})
        self.messages = prune(self.messages, max_tokens=self.max_context_tokens)
```

with (drop the one-time prune; the loop now fits every iteration):

```python
        self.messages.append({"role": "user", "content": user_text})
```

and make `self.messages = self._fit()` the first statement inside the iteration loop:

```python
        for _ in range(self.max_iterations):
            self.messages = self._fit()
            try:
```

(f) In `avadex/cli.py`, extend the `AgentLoop(...)` call (currently lines 174-182) to pass the new fields:

```python
    agent = AgentLoop(
        client=client, registry=registry, permissions=permissions,
        system_prompt=_build_system_prompt(cfg, render_skill_index(skills)),
        max_context_tokens=cfg.max_context_tokens,
        max_response_tokens=cfg.max_response_tokens,
        model=initial_model,
        prompt_user=build_terminal_prompter(),
        max_iterations=cfg.max_iterations,
        compaction_threshold=cfg.context_compaction_threshold,
        large_output_tokens=cfg.context_large_output_tokens,
        keep_recent=cfg.context_keep_recent,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_agent_loop_compaction.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add avadex/agent_loop.py avadex/cli.py tests/unit/test_agent_loop_compaction.py
git commit -m "Wire hybrid context management into AgentLoop and CLI"
```

---

## Task 9: Full-suite verification, changelog, version bump

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `pyproject.toml` (via `scripts/bump_patch.py`)

- [ ] **Step 1: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: PASS — all prior tests plus the new context/config/agent_loop tests green. If any pre-existing `AgentLoop` test broke, confirm it constructs `AgentLoop` without the new params (defaults must keep them passing) and fix only if a real regression.

- [ ] **Step 2: Add a CHANGELOG entry**

Add a new section at the top of `CHANGELOG.md` following the existing format, describing: hybrid context management — deterministic dedup (superseded reads, denied calls, large outputs; errors preserved) plus proactive summarization at a configurable high-water threshold, with new config keys `context_compaction_threshold`, `context_large_output_tokens`, `context_keep_recent`.

- [ ] **Step 3: Bump the version**

Run: `.venv/bin/python scripts/bump_patch.py`
(Confirm the new version in `pyproject.toml`. A minor bump instead of patch is the user's call at release time per their versioning ritual.)

- [ ] **Step 4: Re-run the suite to confirm nothing broke**

Run: `.venv/bin/pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md pyproject.toml
git commit -m "Release hybrid context management"
```

---

## Self-Review Notes

- **Spec coverage:** dedup superseded reads → Task 1; denied calls → Task 2; large outputs + errors preserved → Task 3; dedup coordinator + no-mutation → Task 4; compact + boundary safety + None handling → Task 5; fit_context pipeline (threshold no-op, dedup-only, summarize, prune backstop) → Task 6; config fields → Task 7; per-iteration wiring + `_summarize` callback + cli → Task 8; full-suite + changelog + bump → Task 9. All spec sections covered.
- **Type consistency:** `dedup(messages, *, large_output_tokens, keep_recent)`, `compact(messages, summarizer, *, keep_recent)`, `fit_context(messages, *, max_tokens, threshold, summarizer, large_output_tokens, keep_recent)`, and the `AgentLoop` params (`compaction_threshold`, `large_output_tokens`, `keep_recent`) are used identically across tasks and the cli wiring.
- **No placeholders:** every code step shows complete code; every test step shows the assertions and the run command with expected output.
