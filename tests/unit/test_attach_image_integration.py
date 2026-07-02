"""Cross-cutting checks for the attach_image feature: permission tier and
that the REPL renderer survives list (image) tool-result content."""
from avadex.permissions import PermissionManager, Decision
from avadex.repl import AnsiRenderer
from avadex.tools.registry import ToolResult


def test_attach_image_is_auto_allowed(tmp_path):
    pm = PermissionManager(tmp_path / "missing.toml")
    assert pm.check("attach_image", {"path": "/home/x/pic.png"}) == Decision.AUTO_ALLOW


def test_repl_renderer_handles_list_content(capsys):
    r = AnsiRenderer()
    result = ToolResult(content=[
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}},
        {"type": "text", "text": "attached pic.png"},
    ])
    # Must not raise (result.content.splitlines() would crash on a list).
    r.tool_result("attach_image", result)
    out = capsys.readouterr().out
    assert "AAAA" not in out  # base64 payload never dumped
