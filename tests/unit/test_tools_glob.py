from avadex.tools.builtin import glob_tool


def test_glob_finds_files(tmp_path):
    (tmp_path / "a.py").write_text("")
    (tmp_path / "b.py").write_text("")
    (tmp_path / "c.txt").write_text("")
    result = glob_tool({"pattern": "*.py", "base": str(tmp_path)})
    assert not result.is_error
    assert "a.py" in result.content
    assert "b.py" in result.content
    assert "c.txt" not in result.content


def test_glob_recursive(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deep.py").write_text("")
    result = glob_tool({"pattern": "**/*.py", "base": str(tmp_path)})
    assert "deep.py" in result.content


def test_glob_no_matches(tmp_path):
    result = glob_tool({"pattern": "*.nonexistent", "base": str(tmp_path)})
    assert not result.is_error
    assert "no matches" in result.content.lower()


def test_glob_missing_pattern(tmp_path):
    result = glob_tool({})
    assert result.is_error


def test_glob_caps_at_200(tmp_path):
    for i in range(250):
        (tmp_path / f"f{i}.x").write_text("")
    result = glob_tool({"pattern": "*.x", "base": str(tmp_path)})
    assert "250 matches" in result.content
    assert "showing first 200" in result.content
