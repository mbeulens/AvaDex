from avadex.tools.builtin import edit_file_tool


def test_edit_replaces_unique_string(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("def foo():\n    return 1\n")
    result = edit_file_tool({
        "path": str(f),
        "old_string": "return 1",
        "new_string": "return 42",
    })
    assert not result.is_error
    assert "return 42" in f.read_text()


def test_edit_errors_if_old_not_found(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("hello")
    result = edit_file_tool({
        "path": str(f), "old_string": "missing", "new_string": "x",
    })
    assert result.is_error
    assert "not found" in result.content.lower()


def test_edit_errors_if_old_not_unique(tmp_path):
    f = tmp_path / "x.py"
    f.write_text("a\na\n")
    result = edit_file_tool({
        "path": str(f), "old_string": "a", "new_string": "b",
    })
    assert result.is_error
    assert "not unique" in result.content.lower() or "multiple" in result.content.lower()


def test_edit_missing_file(tmp_path):
    result = edit_file_tool({
        "path": str(tmp_path / "nope"), "old_string": "a", "new_string": "b",
    })
    assert result.is_error
