from pathlib import Path
import pytest
from avadex.config import Config, load_config, save_token, ConfigMissing


def test_load_full_config(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("""
ava_url = "https://ava.example.com"
ava_token = "abc"
default_model = "gemma4"
max_context_tokens = 3000

[[mcp_servers]]
name = "fs"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
""")
    cfg = load_config(p)
    assert cfg.ava_url == "https://ava.example.com"
    assert cfg.ava_token == "abc"
    assert cfg.max_context_tokens == 3000
    assert len(cfg.mcp_servers) == 1
    assert cfg.mcp_servers[0]["name"] == "fs"


def test_load_missing_raises(tmp_path):
    with pytest.raises(ConfigMissing):
        load_config(tmp_path / "nope.toml")


def test_load_uses_defaults_for_unset(tmp_path):
    p = tmp_path / "min.toml"
    p.write_text('ava_url = "u"\nava_token = "t"\n')
    cfg = load_config(p)
    assert cfg.default_model == "gemma4"
    assert cfg.max_context_tokens == 3500
    assert cfg.mcp_servers == []


def test_save_token_writes_minimal_config(tmp_path):
    p = tmp_path / "config.toml"
    save_token(p, "https://x.test", "tkn")
    cfg = load_config(p)
    assert cfg.ava_url == "https://x.test"
    assert cfg.ava_token == "tkn"


def test_load_missing_required_field_raises_config_missing(tmp_path):
    p = tmp_path / "incomplete.toml"
    p.write_text('ava_url = "https://x.test"\n')  # missing ava_token
    with pytest.raises(ConfigMissing, match="ava_token"):
        load_config(p)


def test_save_token_preserves_other_fields(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('''
ava_url = "old"
ava_token = "old"
max_context_tokens = 2000

[[mcp_servers]]
name = "fs"
command = "x"
args = []
''')
    save_token(p, "new", "new")
    cfg = load_config(p)
    assert cfg.ava_url == "new"
    assert cfg.ava_token == "new"
    assert cfg.max_context_tokens == 2000
    assert len(cfg.mcp_servers) == 1
