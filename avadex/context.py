from __future__ import annotations

import copy
import json

SAFETY_FACTOR = 1.2


def estimate_tokens(thing: str | dict | list) -> int:
    """Conservative chars/4 estimator with a 1.2x safety multiplier."""
    if isinstance(thing, str):
        raw = thing
    else:
        raw = json.dumps(thing, separators=(",", ":"))
    return int(len(raw) / 4 * SAFETY_FACTOR)


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
            if isinstance(content, str) and estimate_tokens(content) > large_output_tokens:
                approx = estimate_tokens(content)
                b["content"] = f"[output truncated to save context: ~{approx} tokens]"
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
