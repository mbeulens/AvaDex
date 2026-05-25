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


HTTP_JSON = (
    '{"mcpServers": {"r": {"type": "http", "url": "https://h",'
    ' "headers": {"Authorization": "Bearer ${TOK}"}}}}'
)


def test_resolve_no_mcp_json_returns_global(tmp_path):
    from avadex.mcp_workdir import resolve_mcp_servers
    from avadex.config import Config, MCPServerConfig
    cfg = Config(ava_url="u", ava_token="t",
                 mcp_servers=[MCPServerConfig(name="g", command="x")])
    result = resolve_mcp_servers(cfg, tmp_path)
    assert result is cfg.mcp_servers
    assert [s.name for s in result] == ["g"]


def test_resolve_loads_workdir_servers(tmp_path):
    from avadex.mcp_workdir import resolve_mcp_servers
    from avadex.config import Config
    (tmp_path / ".mcp.json").write_text(
        '{"mcpServers": {"remote": {"type": "http", "url": "https://h"}}}'
    )
    cfg = Config(ava_url="u", ava_token="t")
    result = resolve_mcp_servers(cfg, tmp_path)
    assert len(result) == 1
    assert result[0].name == "remote"
    assert result[0].transport == "http"
    assert result[0].url == "https://h"


def test_resolve_dotenv_wins_over_os_environ(tmp_path, monkeypatch):
    from avadex.mcp_workdir import resolve_mcp_servers
    from avadex.config import Config
    monkeypatch.setenv("TOK", "from_os")
    (tmp_path / ".env").write_text("TOK=from_dotenv\n")
    (tmp_path / ".mcp.json").write_text(HTTP_JSON)
    cfg = Config(ava_url="u", ava_token="t")
    result = resolve_mcp_servers(cfg, tmp_path)
    assert result[0].headers["Authorization"] == "Bearer from_dotenv"


def test_resolve_dotenv_only_var(tmp_path, monkeypatch):
    from avadex.mcp_workdir import resolve_mcp_servers
    from avadex.config import Config
    monkeypatch.delenv("TOK", raising=False)
    (tmp_path / ".env").write_text("TOK=only_dotenv\n")
    (tmp_path / ".mcp.json").write_text(HTTP_JSON)
    cfg = Config(ava_url="u", ava_token="t")
    result = resolve_mcp_servers(cfg, tmp_path)
    assert result[0].headers["Authorization"] == "Bearer only_dotenv"


def test_resolve_malformed_json_raises(tmp_path):
    from avadex.mcp_workdir import resolve_mcp_servers
    from avadex.config import Config, ConfigMissing
    (tmp_path / ".mcp.json").write_text("{ not valid json ")
    cfg = Config(ava_url="u", ava_token="t")
    with pytest.raises(ConfigMissing):
        resolve_mcp_servers(cfg, tmp_path)


def test_resolve_missing_var_raises(tmp_path, monkeypatch):
    from avadex.mcp_workdir import resolve_mcp_servers
    from avadex.config import Config, ConfigMissing
    monkeypatch.delenv("TOK", raising=False)
    (tmp_path / ".mcp.json").write_text(HTTP_JSON)
    cfg = Config(ava_url="u", ava_token="t")
    with pytest.raises(ConfigMissing, match="TOK"):
        resolve_mcp_servers(cfg, tmp_path)


def test_resolve_non_utf8_mcp_json_raises_configmissing(tmp_path):
    from avadex.mcp_workdir import resolve_mcp_servers
    from avadex.config import Config, ConfigMissing
    # Invalid UTF-8 bytes in .mcp.json -> read_text() raises UnicodeDecodeError
    (tmp_path / ".mcp.json").write_bytes(b"\xff\xfe\x00\x01 not text")
    cfg = Config(ava_url="u", ava_token="t")
    with pytest.raises(ConfigMissing):
        resolve_mcp_servers(cfg, tmp_path)


def test_resolve_does_not_mutate_os_environ(tmp_path, monkeypatch):
    import os
    from avadex.mcp_workdir import resolve_mcp_servers
    from avadex.config import Config
    monkeypatch.delenv("TOK", raising=False)
    (tmp_path / ".env").write_text("TOK=only_dotenv\n")
    (tmp_path / ".mcp.json").write_text(HTTP_JSON)
    cfg = Config(ava_url="u", ava_token="t")
    result = resolve_mcp_servers(cfg, tmp_path)
    # The .env value was used for header interpolation...
    assert result[0].headers["Authorization"] == "Bearer only_dotenv"
    # ...but it must NOT have leaked into the real process environment.
    assert "TOK" not in os.environ
