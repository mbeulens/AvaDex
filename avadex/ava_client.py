from __future__ import annotations
import httpx

from avadex.types import AvaResponse, parse_response
from avadex.log import get_logger

log = get_logger("ava_client")


class TokenExpired(Exception):
    pass


class AvaError(Exception):
    pass


class ContextOverflow(AvaError):
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
        log.debug(
            "POST /api/v1/messages model=%s messages=%d tools=%d",
            model, len(messages), len(tools),
        )
        try:
            response = self._client.post(
                f"{self.base_url}/api/v1/messages", json=payload
            )
        except httpx.RequestError as exc:
            log.warning("POST /api/v1/messages network error: %s", exc)
            raise AvaError(f"network error: {exc}") from exc

        if response.status_code == 401:
            log.warning("POST /api/v1/messages got 401 — token rejected")
            raise TokenExpired("token rejected by Ava")
        if response.status_code >= 400:
            body = response.text[:500]
            log.warning("POST /api/v1/messages HTTP %d: %s", response.status_code, body[:200])
            low = body.lower()
            if "does not support tools" in low:
                raise AvaError(
                    f"model {model!r} does not support tool calling — "
                    f"switch to a tool-capable model with /model"
                )
            if "context" in low and ("length" in low or "too" in low or "exceed" in low):
                raise ContextOverflow(f"HTTP {response.status_code}: {body}")
            raise AvaError(f"HTTP {response.status_code}: {body}")
        try:
            raw = response.json()
        except ValueError as exc:
            log.warning("POST /api/v1/messages malformed JSON: %s", exc)
            raise AvaError(f"malformed response (not JSON): {exc}") from exc

        # Detect non-Anthropic 200 responses. Ava is supposed to return
        # {"content": [...], "stop_reason": "...", "model": "...", "usage": {...}}.
        # An Ollama crash or upstream bug can produce a 200 with {"error": ...}
        # or {"type": "error"} — without this check, parse_response would
        # default the missing fields and the REPL would render an empty turn.
        if not isinstance(raw, dict):
            log.warning("POST /api/v1/messages unexpected response shape: %s", str(raw)[:200])
            raise AvaError(f"unexpected response shape (not an object): {str(raw)[:300]}")
        if raw.get("type") == "error" or (
            "error" in raw and "content" not in raw
        ):
            log.warning("POST /api/v1/messages Ava error response: %s", str(raw)[:200])
            raise AvaError(f"Ava returned an error: {str(raw)[:300]}")
        if "content" not in raw and "stop_reason" not in raw:
            log.warning("POST /api/v1/messages missing content/stop_reason: %s", str(raw)[:200])
            raise AvaError(f"unexpected response shape from Ava: {str(raw)[:300]}")

        log.debug(
            "response stop_reason=%s content_blocks=%d",
            raw.get("stop_reason"), len(raw.get("content") or []),
        )
        try:
            return parse_response(raw)
        except (ValueError, KeyError) as exc:
            log.warning("POST /api/v1/messages parse error: %s", exc)
            raise AvaError(f"malformed response: {exc}") from exc

    def list_models(self) -> dict:
        """GET /api/v1/models. Returns {"models": [...], "default": str}.

        Raises TokenExpired on 401, AvaError on other HTTP failures or network errors.
        """
        log.debug("GET /api/v1/models")
        try:
            response = self._client.get(f"{self.base_url}/api/v1/models")
        except httpx.RequestError as exc:
            log.warning("GET /api/v1/models network error: %s", exc)
            raise AvaError(f"network error: {exc}") from exc
        if response.status_code == 401:
            log.warning("GET /api/v1/models got 401 — token rejected")
            raise TokenExpired("token rejected by Ava")
        if response.status_code >= 400:
            body = response.text[:500]
            log.warning("GET /api/v1/models HTTP %d: %s", response.status_code, body[:200])
            raise AvaError(f"HTTP {response.status_code}: {body}")
        try:
            data = response.json()
            result = {
                "models": list(data.get("models", [])),
                "default": data.get("default", ""),
            }
            if isinstance(data.get("ava"), dict):
                result["ava"] = data["ava"]   # the calling key's privacy policy
            log.debug("GET /api/v1/models default=%s count=%d", result["default"], len(result["models"]))
            return result
        except (ValueError, KeyError) as exc:
            log.warning("GET /api/v1/models malformed response: %s", exc)
            raise AvaError(f"malformed response: {exc}") from exc

    def close(self):
        self._client.close()
