from __future__ import annotations
import httpx

from avadex.types import AvaResponse, parse_response


class TokenExpired(Exception):
    pass


class AvaError(Exception):
    pass


class AvaClient:
    def __init__(self, base_url: str, token: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._client = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
        )

    def messages(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 2048,
        model: str = "gemma4",
    ) -> AvaResponse:
        payload = {
            "model": model,
            "system": system,
            "messages": messages,
            "tools": tools,
            "max_tokens": max_tokens,
        }
        try:
            response = self._client.post(
                f"{self.base_url}/api/v1/messages", json=payload
            )
        except httpx.RequestError as exc:
            raise AvaError(f"network error: {exc}") from exc

        if response.status_code == 401:
            raise TokenExpired("token rejected by Ava")
        if response.status_code >= 400:
            body = response.text[:500]
            raise AvaError(f"HTTP {response.status_code}: {body}")
        try:
            return parse_response(response.json())
        except (ValueError, KeyError) as exc:
            raise AvaError(f"malformed response: {exc}") from exc

    def close(self):
        self._client.close()
