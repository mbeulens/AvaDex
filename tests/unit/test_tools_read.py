from avadex.tools.builtin import read_file_tool


def test_read_file_returns_contents(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("hi there")
    result = read_file_tool({"path": str(f)})
    assert result.content == "hi there"
    assert not result.is_error


def test_read_file_missing_returns_error(tmp_path):
    result = read_file_tool({"path": str(tmp_path / "nope")})
    assert result.is_error
    assert "not found" in result.content.lower() or "no such" in result.content.lower()


def test_read_file_size_cap(tmp_path):
    f = tmp_path / "big.txt"
    f.write_bytes(b"x" * (2 * 1024 * 1024))  # 2 MB > 1 MB cap
    result = read_file_tool({"path": str(f)})
    assert result.is_error
    assert "too large" in result.content.lower()
