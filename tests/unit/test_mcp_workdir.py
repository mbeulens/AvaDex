import pytest


def test_load_dotenv_parses_keys_quotes_comments_export(tmp_path):
    from avadex.mcp_workdir import load_dotenv
    p = tmp_path / ".env"
    p.write_text(
        "FOO=bar\n"
        "# a comment\n"
        "\n"
        "export BAZ=qux\n"
        'QUOTED="hello world"\n'
        "SINGLE='abc'\n"
        "noequalsline\n"
    )
    env = load_dotenv(p)
    assert env == {
        "FOO": "bar",
        "BAZ": "qux",
        "QUOTED": "hello world",
        "SINGLE": "abc",
    }


def test_load_dotenv_missing_file_returns_empty(tmp_path):
    from avadex.mcp_workdir import load_dotenv
    assert load_dotenv(tmp_path / "nope.env") == {}
