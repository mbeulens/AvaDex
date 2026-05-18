import json
import pytest
import httpx
from avadex.ava_client import AvaClient, TokenExpired, AvaError


def test_messages_sends_correct_request(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://ava.test/api/v1/messages",
        json={
            "content": [{"type": "text", "text": "hi"}],
            "model": "gemma4",
            "stop_reason": "end_turn",
            "usage": {},
        },
    )
    client = AvaClient("https://ava.test", "tkn")
    resp = client.messages(
        system="sys",
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
    )
    assert resp.stop_reason == "end_turn"

    request = httpx_mock.get_request()
    assert request.headers["Authorization"] == "Bearer tkn"
    body = json.loads(request.content)
    assert body["model"] == "gemma4"
    assert body["system"] == "sys"
    assert body["messages"] == [{"role": "user", "content": "hello"}]


def test_messages_401_raises_token_expired(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://ava.test/api/v1/messages",
        status_code=401,
        json={"error": "unauthorized"},
    )
    client = AvaClient("https://ava.test", "bad")
    with pytest.raises(TokenExpired):
        client.messages(system="", messages=[{"role": "user", "content": "x"}], tools=[])


def test_messages_500_raises_ava_error(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://ava.test/api/v1/messages",
        status_code=500,
        text="boom",
    )
    client = AvaClient("https://ava.test", "tkn")
    with pytest.raises(AvaError, match="500"):
        client.messages(system="", messages=[{"role": "user", "content": "x"}], tools=[])


def test_messages_includes_tools_when_provided(httpx_mock):
    httpx_mock.add_response(
        method="POST",
        url="https://ava.test/api/v1/messages",
        json={
            "content": [{"type": "text", "text": "ok"}],
            "model": "gemma4",
            "stop_reason": "end_turn",
            "usage": {},
        },
    )
    client = AvaClient("https://ava.test", "tkn")
    client.messages(
        system="",
        messages=[{"role": "user", "content": "x"}],
        tools=[{"name": "read_file", "description": "", "input_schema": {}}],
    )
    body = json.loads(httpx_mock.get_request().content)
    assert body["tools"][0]["name"] == "read_file"
