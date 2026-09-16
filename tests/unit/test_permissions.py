from pathlib import Path
from avadex.permissions import PermissionManager, Decision, Rule


def write_allowlist(path: Path, rules: list[Rule]):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for r in rules:
        lines.append("[[rules]]")
        lines.append(f'tool = "{r.tool}"')
        lines.append(f'pattern = "{r.pattern}"')
        lines.append("")
    path.write_text("\n".join(lines))


def test_read_only_tools_auto_allow_without_allowlist(tmp_path):
    pm = PermissionManager(tmp_path / "missing.toml")
    assert pm.check("read_file", {"path": "/etc/hostname"}) == Decision.AUTO_ALLOW


def test_unknown_write_tool_prompts(tmp_path):
    pm = PermissionManager(tmp_path / "missing.toml")
    assert pm.check("bash", {"command": "rm -rf /"}) == Decision.PROMPT


def test_allowlisted_pattern_auto_allows(tmp_path):
    p = tmp_path / "allow.toml"
    write_allowlist(p, [Rule(tool="bash", pattern="git status")])
    pm = PermissionManager(p)
    assert pm.check("bash", {"command": "git status"}) == Decision.AUTO_ALLOW


def test_glob_pattern_auto_allows(tmp_path):
    p = tmp_path / "allow.toml"
    write_allowlist(p, [Rule(tool="bash", pattern="ls *")])
    pm = PermissionManager(p)
    assert pm.check("bash", {"command": "ls -la /tmp"}) == Decision.AUTO_ALLOW
    assert pm.check("bash", {"command": "rm /tmp/x"}) == Decision.PROMPT


def test_add_rule_persists_to_disk(tmp_path):
    p = tmp_path / "allow.toml"
    pm = PermissionManager(p)
    pm.add_rule(Rule(tool="bash", pattern="systemctl restart *"))
    pm2 = PermissionManager(p)
    assert pm2.check(
        "bash", {"command": "systemctl restart nginx"}
    ) == Decision.AUTO_ALLOW


def test_rules_from_both_files_are_merged(tmp_path):
    g = tmp_path / "global.toml"
    w = tmp_path / "proj" / ".avadex" / "allowlist.toml"
    write_allowlist(g, [Rule(tool="bash", pattern="git status")])
    write_allowlist(w, [Rule(tool="bash", pattern="npm test *")])
    pm = PermissionManager(g, w)
    assert pm.check("bash", {"command": "git status"}) == Decision.AUTO_ALLOW
    assert pm.check("bash", {"command": "npm test -- --watch"}) == Decision.AUTO_ALLOW
    assert pm.check("bash", {"command": "rm -rf /"}) == Decision.PROMPT


def test_missing_workdir_allowlist_falls_back_to_global_only(tmp_path):
    g = tmp_path / "global.toml"
    write_allowlist(g, [Rule(tool="bash", pattern="git status")])
    pm = PermissionManager(g, tmp_path / "proj" / ".avadex" / "allowlist.toml")
    assert pm.check("bash", {"command": "git status"}) == Decision.AUTO_ALLOW


def test_add_rule_writes_to_workdir_and_leaves_global_untouched(tmp_path):
    g = tmp_path / "global.toml"
    w = tmp_path / "proj" / ".avadex" / "allowlist.toml"
    write_allowlist(g, [Rule(tool="bash", pattern="git status")])
    before = g.read_bytes()

    pm = PermissionManager(g, w)
    pm.add_rule(Rule(tool="bash", pattern="docker compose *"))

    assert g.read_bytes() == before, "global allowlist must not be rewritten"
    assert w.exists(), "workdir allowlist should be created on demand"
    assert "docker compose *" in w.read_text()
    assert "git status" not in w.read_text(), "global rules must not leak into workdir file"


def test_added_workdir_rule_survives_reload(tmp_path):
    g = tmp_path / "global.toml"
    w = tmp_path / "proj" / ".avadex" / "allowlist.toml"
    pm = PermissionManager(g, w)
    pm.add_rule(Rule(tool="bash", pattern="pytest *"))
    assert not g.exists(), "global file should not be created when workdir is active"
    reloaded = PermissionManager(g, w)
    assert reloaded.check("bash", {"command": "pytest -q"}) == Decision.AUTO_ALLOW


def test_add_rule_without_workdir_still_writes_global(tmp_path):
    g = tmp_path / "global.toml"
    pm = PermissionManager(g)
    pm.add_rule(Rule(tool="bash", pattern="ls *"))
    assert "ls *" in g.read_text()


def test_rules_property_lists_global_then_workdir(tmp_path):
    g = tmp_path / "global.toml"
    w = tmp_path / "w.toml"
    write_allowlist(g, [Rule(tool="bash", pattern="a")])
    write_allowlist(w, [Rule(tool="bash", pattern="b")])
    pm = PermissionManager(g, w)
    assert [r.pattern for r in pm.rules] == ["a", "b"]
