from avadex.tools.builtin import grep_files_tool


def test_grep_finds_matches(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    return 1\n")
    (tmp_path / "b.py").write_text("def bar():\n    pass\n")
    result = grep_files_tool({"pattern": r"def \w+", "base": str(tmp_path), "path_glob": "*.py"})
    assert not result.is_error
    assert "def foo" in result.content
    assert "def bar" in result.content


def test_grep_no_matches(tmp_path):
    (tmp_path / "a.py").write_text("hello\n")
    result = grep_files_tool({"pattern": "xyzzy", "base": str(tmp_path)})
    assert "no matches" in result.content.lower()


def test_grep_invalid_regex(tmp_path):
    result = grep_files_tool({"pattern": "[unclosed", "base": str(tmp_path)})
    assert result.is_error
    assert "invalid regex" in result.content.lower()


def test_grep_missing_pattern(tmp_path):
    result = grep_files_tool({})
    assert result.is_error


def test_grep_respects_max_results(tmp_path):
    (tmp_path / "big.txt").write_text("\n".join(["match"] * 50))
    result = grep_files_tool({"pattern": "match", "base": str(tmp_path), "max_results": 5})
    # Should report exactly 5 capped matches
    assert "5 matches" in result.content
    assert "capped" in result.content


def test_grep_includes_line_numbers(tmp_path):
    (tmp_path / "f.txt").write_text("alpha\nbeta\ngamma\n")
    result = grep_files_tool({"pattern": "beta", "base": str(tmp_path)})
    # Line 2 should appear in the result
    assert ":2:" in result.content
