import pytest
from avadex.tools.todos import (
    todo_write_tool, todo_read_tool, _reset_for_tests,
)


@pytest.fixture(autouse=True)
def _clear_todos():
    _reset_for_tests()
    yield
    _reset_for_tests()


def test_todo_write_stores_list():
    result = todo_write_tool({
        "todos": [
            {"content": "ship Tier 1", "status": "completed"},
            {"content": "ship Tier 2a", "status": "in_progress"},
            {"content": "ship Tier 2b", "status": "pending"},
        ],
    })
    assert not result.is_error
    assert "3 todos" in result.content
    assert "ship Tier 1" in result.content


def test_todo_write_then_read():
    todo_write_tool({"todos": [{"content": "alpha", "status": "pending"}]})
    result = todo_read_tool({})
    assert "alpha" in result.content
    assert "[ ]" in result.content   # pending symbol


def test_todo_read_when_empty():
    result = todo_read_tool({})
    assert "no todos" in result.content.lower()


def test_todo_write_replaces_existing():
    todo_write_tool({"todos": [{"content": "first", "status": "pending"}]})
    todo_write_tool({"todos": [{"content": "second", "status": "pending"}]})
    result = todo_read_tool({})
    assert "first" not in result.content
    assert "second" in result.content


def test_todo_write_validates_status():
    result = todo_write_tool({"todos": [{"content": "x", "status": "bogus"}]})
    assert result.is_error
    assert "status" in result.content.lower()


def test_todo_write_validates_content():
    result = todo_write_tool({"todos": [{"content": "", "status": "pending"}]})
    assert result.is_error


def test_todo_write_rejects_non_list():
    result = todo_write_tool({"todos": "not a list"})
    assert result.is_error


def test_todo_write_rejects_non_object_items():
    result = todo_write_tool({"todos": ["just a string"]})
    assert result.is_error


def test_todo_write_default_status_is_pending():
    result = todo_write_tool({"todos": [{"content": "x"}]})
    assert not result.is_error
    read = todo_read_tool({})
    assert "[ ]" in read.content
