from __future__ import annotations

import copy
import json
from typing import Callable

SAFETY_FACTOR = 1.2
# Flat per-image cost. Base64 image payloads are huge (a 1 MB image ~= 1.3M
# chars) but Ollama sends them out-of-band to the vision model, not as text
# tokens. Counting the raw base64 would blow the context budget and make the
# fitter prune away the image. Charge a nominal, fixed cost instead.
NOMINAL_IMAGE_TOKENS = 1500


def _strip_image_payloads(obj):
    """Return (copy of obj with any base64 image data blanked, image_count).
    Recurses through dicts/lists; leaves everything else untouched."""
    if isinstance(obj, dict):
        if obj.get("type") == "image" and isinstance(obj.get("source"), dict) and obj["source"].get("data"):
            return {**obj, "source": {**obj["source"], "data": ""}}, 1
        count = 0
        new = {}
        for k, v in obj.items():
            nv, c = _strip_image_payloads(v)
            new[k] = nv
            count += c
        return new, count
    if isinstance(obj, list):
        count = 0
        new = []
        for item in obj:
            ni, c = _strip_image_payloads(item)
            new.append(ni)
            count += c
        return new, count
    return obj, 0


def estimate_tokens(thing: str | dict | list) -> int:
    """Conservative chars/4 estimator with a 1.2x safety multiplier.

    Base64 image payloads are counted at a flat NOMINAL_IMAGE_TOKENS each
    rather than by their (enormous) character length."""
    if isinstance(thing, str):
        return int(len(thing) / 4 * SAFETY_FACTOR)
    stripped, n_images = _strip_image_payloads(thing)
    raw = json.dumps(stripped, separators=(",", ":"))
    return int(len(raw) / 4 * SAFETY_FACTOR) + n_images * NOMINAL_IMAGE_TOKENS


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
            if not isinstance(content, str):
                continue
            approx = estimate_tokens(content)
            if approx > large_output_tokens:
                b["content"] = f"[output truncated to save context: ~{approx} tokens]"
    return messages


def dedup(messages: list[dict], *, large_output_tokens: int, keep_recent: int) -> list[dict]:
    """Reclaim context space from redundant content without an LLM call.

    Operates on a deep copy so the caller's messages are never mutated.
    """
    msgs = copy.deepcopy(messages)
    msgs = _stub_superseded_reads(msgs, keep_recent)
    msgs = _drop_denied_calls(msgs, keep_recent)
    msgs = _stub_large_outputs(msgs, large_output_tokens, keep_recent)
    return msgs


def _starts_with_tool_result(message: dict) -> bool:
    c = message.get("content")
    return isinstance(c, list) and any(b.get("type") == "tool_result" for b in c)


def compact(messages: list[dict], summarizer: "Callable[[list[dict]], str | None]",
            *, keep_recent: int) -> list[dict]:
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
    while 0 < cut < n and _starts_with_tool_result(messages[cut]):
        cut -= 1
    if cut <= 0:
        return messages
    old, recent = messages[:cut], messages[cut:]
    summary = summarizer(old)
    if summary is None:
        return messages
    summary_msg = {"role": "user", "content": f"[Earlier conversation summary]\n{summary}"}
    return [summary_msg] + recent


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


def _tool_use_ids(message: dict) -> set[str]:
    c = message.get("content", "")
    if not isinstance(c, list):
        return set()
    return {b["id"] for b in c if b.get("type") == "tool_use" and b.get("id")}


def _tool_result_ids(message: dict) -> set[str]:
    c = message.get("content", "")
    if not isinstance(c, list):
        return set()
    return {
        b["tool_use_id"]
        for b in c
        if b.get("type") == "tool_result" and b.get("tool_use_id")
    }


def prune(messages: list[dict], max_tokens: int) -> list[dict]:
    """Drop oldest messages until total token estimate fits the budget.

    Invariants:
      - Always keeps the most recent message, even if it alone exceeds budget.
      - tool_use and matching tool_result messages are dropped together.
    """
    if not messages:
        return messages

    # Build pairing index: tool_use_id -> indices of messages that reference it
    pair_index: dict[str, set[int]] = {}
    for i, m in enumerate(messages):
        for tid in _tool_use_ids(m) | _tool_result_ids(m):
            if tid:
                pair_index.setdefault(tid, set()).add(i)

    kept = list(range(len(messages)))
    total = sum(estimate_tokens(messages[i]) for i in kept)

    while total > max_tokens and len(kept) > 1:
        # Find the oldest index, expand to its full tool pair group
        oldest = kept[0]
        group = {oldest}
        for tid in _tool_use_ids(messages[oldest]) | _tool_result_ids(messages[oldest]):
            if tid in pair_index:
                group |= pair_index[tid]
        # Don't drop the most recent message
        if max(kept) in group:
            break
        for idx in group:
            if idx in kept:
                kept.remove(idx)
                total -= estimate_tokens(messages[idx])

    return [messages[i] for i in sorted(kept)]
