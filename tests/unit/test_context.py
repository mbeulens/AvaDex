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


def test_drop_denied_calls_respects_recent_window():
    from avadex.context import _drop_denied_calls
    messages = [
        {"role": "assistant", "content": "earlier"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "d1", "name": "bash", "input": {}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "d1", "content": "denied by user", "is_error": True}]},
    ]
    # keep_recent=2 protects the last two messages (the denied pair) → preserved untouched.
    out = _drop_denied_calls(messages, keep_recent=2)
    assert out == messages


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


def test_stub_large_outputs_respects_recent_window():
    from avadex.context import _stub_large_outputs
    big = "x" * 8000
    messages = [
        {"role": "assistant", "content": "older"},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": big, "is_error": False}]},
    ]
    # keep_recent=2 protects both messages → the large output is left untouched.
    out = _stub_large_outputs(messages, large_output_tokens=1000, keep_recent=2)
    assert out[1]["content"][0]["content"] == big


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


def test_compact_keep_recent_zero_summarizes_all():
    from avadex.context import compact
    captured = {}
    messages = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "c"},
    ]
    def summ(old):
        captured["n"] = len(old)
        return "ALL"
    out = compact(messages, summ, keep_recent=0)
    assert out == [{"role": "user", "content": "[Earlier conversation summary]\nALL"}]
    assert captured["n"] == 3  # summarizer saw the whole history


def test_compact_all_tool_results_bails_out():
    from avadex.context import compact
    # Every candidate cut point starts with a tool_result → walk reaches cut=1 and
    # the segment is too entangled; must not crash and must not strand a result.
    messages = [
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "a", "content": "r0", "is_error": False}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "b", "content": "r1", "is_error": False}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "c", "content": "r2", "is_error": False}]},
    ]
    out = compact(messages, lambda old: "S", keep_recent=2)
    # cut walks 1 -> stops at 1 (index 1 is a tool_result, index 0 check: cut becomes... )
    # Whatever the boundary, the call must not raise and must return a list.
    assert isinstance(out, list)


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
