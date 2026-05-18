from avadex.tools.builtin import multi_edit_tool


def test_multi_edit_applies_all(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("def foo():\n    return 1\n\ndef bar():\n    return 2\n")
    result = multi_edit_tool({
        "path": str(f),
        "edits": [
            {"old_string": "return 1", "new_string": "return 11"},
            {"old_string": "return 2", "new_string": "return 22"},
        ],
    })
    assert not result.is_error
    body = f.read_text()
    assert "return 11" in body
    assert "return 22" in body


def test_multi_edit_atomic_on_missing_old_string(tmp_path):
    f = tmp_path / "a.py"
    original = "alpha\nbeta\n"
    f.write_text(original)
    result = multi_edit_tool({
        "path": str(f),
        "edits": [
            {"old_string": "alpha", "new_string": "ALPHA"},
            {"old_string": "missing", "new_string": "x"},  # this fails
        ],
    })
    assert result.is_error
    assert "edit 2" in result.content
    # File unchanged because edit 2 failed
    assert f.read_text() == original


def test_multi_edit_atomic_on_non_unique_old_string(tmp_path):
    f = tmp_path / "a.py"
    original = "x\nx\ny\n"
    f.write_text(original)
    result = multi_edit_tool({
        "path": str(f),
        "edits": [
            {"old_string": "y", "new_string": "Y"},
            {"old_string": "x", "new_string": "X"},  # x appears 2x
        ],
    })
    assert result.is_error
    assert "edit 2" in result.content
    assert "appears 2 times" in result.content or "must be unique" in result.content
    assert f.read_text() == original


def test_multi_edit_sequential_state(tmp_path):
    """Later edits see the result of earlier edits."""
    f = tmp_path / "a.py"
    f.write_text("foo\nfoo bar\n")
    result = multi_edit_tool({
        "path": str(f),
        "edits": [
            {"old_string": "foo bar", "new_string": "baz qux"},   # removes one 'foo'
            {"old_string": "foo", "new_string": "FOO"},            # now foo is unique
        ],
    })
    assert not result.is_error
    assert f.read_text() == "FOO\nbaz qux\n"


def test_multi_edit_missing_args(tmp_path):
    assert multi_edit_tool({}).is_error
    assert multi_edit_tool({"path": str(tmp_path / "f")}).is_error
    assert multi_edit_tool({"path": str(tmp_path / "f"), "edits": []}).is_error


def test_multi_edit_missing_file(tmp_path):
    result = multi_edit_tool({
        "path": str(tmp_path / "nope"),
        "edits": [{"old_string": "a", "new_string": "b"}],
    })
    assert result.is_error


def test_multi_edit_bad_edit_shape(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("hi")
    result = multi_edit_tool({
        "path": str(f),
        "edits": [{"only_old": "hi"}],
    })
    assert result.is_error
