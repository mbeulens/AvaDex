from __future__ import annotations

import json

SAFETY_FACTOR = 1.2


def estimate_tokens(thing: str | dict | list) -> int:
    """Conservative chars/4 estimator with a 1.2x safety multiplier."""
    if isinstance(thing, str):
        raw = thing
    else:
        raw = json.dumps(thing, separators=(",", ":"))
    return int(len(raw) / 4 * SAFETY_FACTOR)


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
