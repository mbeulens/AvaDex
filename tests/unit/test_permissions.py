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
