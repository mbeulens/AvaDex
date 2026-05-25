import pytest
from avadex.ava_client import AvaClient, AvaError

_NO_TOOLS_BODY = (
    '{"type": "error", "error": {"type": "request_error", "message": '
    '"deepseek-coder-v2:16b does not support tools (status code: 400)"}}'
)


def test_friendly_error_on_no_tool_support_400(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://ava.test/api/v1/messages",
        status_code=400,
        text=_NO_TOOLS_BODY,
    )
    client = AvaClient("https://ava.test", "tkn")
    with pytest.raises(AvaError) as exc:
        client.messages(
            system="", messages=[{"role": "user", "content": "x"}],
            tools=[{"name": "write_file"}], model="deepseek-coder-v2:16b",
        )
    msg = str(exc.value)
    assert "deepseek-coder-v2:16b" in msg
    assert "/model" in msg
    assert "tool" in msg.lower()
    # The raw HTTP/JSON blob should NOT be what the user sees.
    assert "status code: 400" not in msg


def test_friendly_error_on_no_tool_support_500(httpx_mock):
    # Before the Ava-side cleanup this arrives as a 500; detection must still fire.
    httpx_mock.add_response(
        method="POST",
        url="https://ava.test/api/v1/messages",
        status_code=500,
        text=_NO_TOOLS_BODY,
    )
    client = AvaClient("https://ava.test", "tkn")
    with pytest.raises(AvaError) as exc:
        client.messages(
            system="", messages=[{"role": "user", "content": "x"}],
            tools=[{"name": "write_file"}], model="deepseek-coder-v2:16b",
        )
    assert "/model" in str(exc.value)
