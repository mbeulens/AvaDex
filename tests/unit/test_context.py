from avadex.context import estimate_tokens, prune


def test_estimate_tokens_simple_string():
    # Heuristic: chars / 4 * safety factor (1.2)
    # 400 chars / 4 * 1.2 = 120 tokens
    assert estimate_tokens("abcd" * 100) == 120


def test_estimate_tokens_message_includes_content_and_role():
    msg = {"role": "user", "content": "abcd" * 25}  # 100 chars
    # JSON overhead: ~32 chars, total ~132, then 132/4 * 1.2 = ~39.6 tokens
    assert 35 <= estimate_tokens(msg) <= 45


def test_prune_under_budget_is_noop():
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    out = prune(messages, max_tokens=1000)
    assert out == messages


def test_prune_drops_oldest_pairs_first():
    messages = [
        {"role": "user", "content": "x" * 4000},      # ~1000 tokens
        {"role": "assistant", "content": "x" * 4000}, # ~1000 tokens
        {"role": "user", "content": "y" * 400},       # ~100 tokens
        {"role": "assistant", "content": "y" * 400},  # ~100 tokens
    ]
    out = prune(messages, max_tokens=300)
    # Oldest 2000-token pair must be dropped, newest kept
    assert len(out) == 2
    assert out[0]["content"].startswith("y")


def test_prune_keeps_tool_use_and_result_together():
    messages = [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "tu_1", "name": "bash", "input": {}}
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "tu_1", "content": "ok"}
        ]},
        {"role": "assistant", "content": "done"},
    ]
    # Force pruning: budget tiny
    out = prune(messages, max_tokens=10)
    # Either both tool_use + tool_result are kept, or both are dropped.
    has_use = any(
        isinstance(m["content"], list) and any(
            b.get("type") == "tool_use" for b in m["content"]
        ) for m in out
    )
    has_result = any(
        isinstance(m["content"], list) and any(
            b.get("type") == "tool_result" for b in m["content"]
        ) for m in out
    )
    assert has_use == has_result


def test_prune_never_returns_empty():
    messages = [{"role": "user", "content": "x" * 100000}]
    out = prune(messages, max_tokens=10)
    # Last message is always kept even if it exceeds budget
    assert len(out) == 1


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
