from avadex.tools.builtin import write_file_tool


def test_write_file_creates_new(tmp_path):
    f = tmp_path / "new.txt"
    result = write_file_tool({"path": str(f), "content": "hi"})
    assert not result.is_error
    assert f.read_text() == "hi"


def test_write_file_overwrites(tmp_path):
    f = tmp_path / "old.txt"
    f.write_text("before")
    result = write_file_tool({"path": str(f), "content": "after"})
    assert not result.is_error
    assert f.read_text() == "after"


def test_write_file_creates_parent_dirs(tmp_path):
    f = tmp_path / "deep" / "nested" / "file.txt"
    result = write_file_tool({"path": str(f), "content": "x"})
    assert not result.is_error
    assert f.read_text() == "x"


def test_write_file_missing_args_errors(tmp_path):
    result = write_file_tool({"path": str(tmp_path / "f")})  # no content
    assert result.is_error
