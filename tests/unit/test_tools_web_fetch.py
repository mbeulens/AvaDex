from avadex.tools.builtin import web_fetch_tool


def test_web_fetch_returns_body(httpx_mock):
    httpx_mock.add_response(url="https://x.test/", text="hello world")
    result = web_fetch_tool({"url": "https://x.test/"})
    assert not result.is_error
    assert "hello world" in result.content


def test_web_fetch_404_is_error(httpx_mock):
    httpx_mock.add_response(url="https://x.test/missing", status_code=404, text="nope")
    result = web_fetch_tool({"url": "https://x.test/missing"})
    assert result.is_error
    assert "404" in result.content


def test_web_fetch_truncates_long_body(httpx_mock):
    body = "x" * 200_000
    httpx_mock.add_response(url="https://x.test/big", text=body)
    result = web_fetch_tool({"url": "https://x.test/big", "max_bytes": 1000})
    assert not result.is_error
    assert len(result.content) < 1500   # truncated body + note
    assert "truncated" in result.content


def test_web_fetch_rejects_non_http(tmp_path):
    result = web_fetch_tool({"url": "file:///etc/passwd"})
    assert result.is_error
    assert "http" in result.content.lower()


def test_web_fetch_missing_url(tmp_path):
    result = web_fetch_tool({})
    assert result.is_error
