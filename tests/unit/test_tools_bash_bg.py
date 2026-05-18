import time
import pytest
from avadex.tools.bash_bg import (
    bash_bg_tool, bash_output_tool, kill_bash_tool, bash_list_tool,
    _reset_for_tests,
)


@pytest.fixture(autouse=True)
def _clear_jobs():
    _reset_for_tests()
    yield
    _reset_for_tests()


def _wait_for(predicate, timeout=5.0, interval=0.05):
    """Poll until predicate() is true, or timeout."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_bash_bg_starts_and_outputs():
    start = bash_bg_tool({"command": "echo hello && sleep 0.2 && echo world"})
    assert not start.is_error
    job_id = start.content.split()[1].rstrip(":")
    # Wait for output to accumulate
    assert _wait_for(lambda: "world" in bash_output_tool({"job_id": job_id}).content)
    result = bash_output_tool({"job_id": job_id})
    assert "hello" in result.content
    assert "world" in result.content
    # Process eventually exits cleanly
    assert _wait_for(lambda: "exited" in bash_output_tool({"job_id": job_id}).content)


def test_bash_bg_missing_command():
    assert bash_bg_tool({}).is_error


def test_bash_output_unknown_job():
    result = bash_output_tool({"job_id": "bgnope"})
    assert result.is_error


def test_kill_bash_terminates_running_process():
    start = bash_bg_tool({"command": "sleep 30"})
    job_id = start.content.split()[1].rstrip(":")
    killed = kill_bash_tool({"job_id": job_id})
    assert not killed.is_error
    assert "terminated" in killed.content
    # Output query should now show exited
    out = bash_output_tool({"job_id": job_id})
    assert "exited" in out.content


def test_kill_bash_unknown_job():
    assert kill_bash_tool({"job_id": "bgnope"}).is_error


def test_kill_bash_already_exited():
    start = bash_bg_tool({"command": "true"})
    job_id = start.content.split()[1].rstrip(":")
    assert _wait_for(lambda: "exited" in bash_output_tool({"job_id": job_id}).content)
    result = kill_bash_tool({"job_id": job_id})
    # Not an error — just a benign note
    assert not result.is_error
    assert "already exited" in result.content


def test_bash_list_empty():
    result = bash_list_tool({})
    assert "no background jobs" in result.content.lower()


def test_bash_list_shows_jobs():
    bash_bg_tool({"command": "sleep 0.5"})
    bash_bg_tool({"command": "echo hi"})
    result = bash_list_tool({})
    assert "sleep" in result.content
    assert "echo hi" in result.content


def test_bash_output_tail_lines():
    """Long output is truncated to tail_lines."""
    start = bash_bg_tool({"command": "for i in $(seq 1 100); do echo line_$i; done"})
    job_id = start.content.split()[1].rstrip(":")
    # Wait for completion
    assert _wait_for(lambda: "exited" in bash_output_tool({"job_id": job_id}).content)
    result = bash_output_tool({"job_id": job_id, "tail_lines": 5})
    # Should contain the LAST 5 lines (line_96..line_100), not the first
    assert "line_100" in result.content
    assert "line_1\n" not in result.content   # first line shouldn't appear
