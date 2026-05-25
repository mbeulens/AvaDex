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


def test_claude_to_raw_maps_type_to_transport():
    from avadex.mcp_workdir import claude_to_raw
    data = {"mcpServers": {
        "remote": {"type": "http", "url": "https://h", "headers": {"A": "B"}},
        "local": {"command": "npx", "args": ["-y", "srv"]},  # no type -> stdio
    }}
    by_name = {r["name"]: r for r in claude_to_raw(data)}
    assert by_name["remote"]["transport"] == "http"
    assert by_name["remote"]["url"] == "https://h"
    assert by_name["remote"]["headers"] == {"A": "B"}
    assert by_name["local"]["transport"] == "stdio"
    assert by_name["local"]["command"] == "npx"
    assert by_name["local"]["args"] == ["-y", "srv"]


def test_claude_to_raw_empty_returns_empty_list():
    from avadex.mcp_workdir import claude_to_raw
    assert claude_to_raw({}) == []
