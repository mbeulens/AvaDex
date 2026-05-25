from __future__ import annotations
import asyncio
import threading
from typing import Optional

from avadex.tools.registry import ToolDefinition, ToolRegistry, ToolResult
from avadex.log import get_logger

log = get_logger("mcp")


def _open_transport(client: "MCPClient"):
    """Return the SDK async context manager for the client's transport.

    Calling the SDK client factory does not open a connection; the connection
    happens when the returned context manager is entered.
    """
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.sse import sse_client
    from mcp.client.streamable_http import streamablehttp_client

    if client.transport == "stdio":
        return stdio_client(StdioServerParameters(command=client.command, args=client.args))
    if client.transport == "http":
        return streamablehttp_client(client.url, headers=client.headers or None)
    if client.transport == "sse":
        return sse_client(client.url, headers=client.headers or None)
    raise ValueError(f"unknown MCP transport {client.transport!r}")


class MCPClient:
    """Synchronous facade over the async mcp Python SDK (stdio, http, and sse transports).

    Owns a background asyncio loop so the rest of AvaDex can stay sync.
    """

    def __init__(self, name: str, transport: str = "stdio",
                 command: Optional[str] = None, args: Optional[list[str]] = None,
                 url: Optional[str] = None,
                 headers: Optional[dict[str, str]] = None):
        self.name = name
        self.transport = transport
        self.command = command or ""
        self.args = args or []
        self.url = url or ""
        self.headers = headers or {}
        self.is_healthy: bool = True
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._session = None  # mcp.ClientSession
        self._exit_stack = None
        self._tools_cache: list[dict] = []

    def start(self):
        from mcp import ClientSession
        from contextlib import AsyncExitStack

        self._loop = asyncio.new_event_loop()

        def _run():
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

        async def _setup():
            self._exit_stack = AsyncExitStack()
            transport = await self._exit_stack.enter_async_context(_open_transport(self))
            read, write = transport[0], transport[1]
            self._session = await self._exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await self._session.initialize()
            listed = await self._session.list_tools()
            self._tools_cache = [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "input_schema": t.inputSchema or {"type": "object"},
                }
                for t in listed.tools
            ]

        fut = asyncio.run_coroutine_threadsafe(_setup(), self._loop)
        fut.result(timeout=30)

    def list_tools(self) -> list[dict]:
        return list(self._tools_cache)

    def call_tool(self, name: str, args: dict) -> ToolResult:
        async def _call():
            result = await self._session.call_tool(name, args)
            # Concatenate text content blocks
            chunks = []
            is_error = bool(getattr(result, "isError", False))
            for c in getattr(result, "content", []):
                t = getattr(c, "text", None)
                if t:
                    chunks.append(t)
            return ToolResult(content="\n".join(chunks) or "(no output)", is_error=is_error)

        fut = asyncio.run_coroutine_threadsafe(_call(), self._loop)
        try:
            return fut.result(timeout=120)
        except Exception as exc:
            # Flip unhealthy on the first failure and warn the user once.
            was_healthy = self.is_healthy
            self.is_healthy = False
            if was_healthy:
                log.warning(
                    "MCP server '%s' crashed — disabling its tools for the rest of "
                    "this session (%s: %s)",
                    self.name, type(exc).__name__, exc,
                )
            return ToolResult(
                content=f"MCP server '{self.name}' is unavailable (crashed: {exc})",
                is_error=True,
            )

    def stop(self):
        if not self._loop:
            return
        async def _close():
            if self._exit_stack is not None:
                await self._exit_stack.aclose()
        try:
            fut = asyncio.run_coroutine_threadsafe(_close(), self._loop)
            fut.result(timeout=10)
        except RuntimeError as exc:
            # anyio's cancel scopes are task-bound; because _setup and _close
            # run on different ephemeral tasks (each spawned by
            # run_coroutine_threadsafe), aclose() complains. The subprocess
            # is still terminated below when the daemon thread exits with
            # the loop, so swallow this specific error and move on.
            if "cancel scope" not in str(exc):
                raise
        except Exception:
            pass
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)


def register_mcp_tools(clients: list, registry: ToolRegistry) -> None:
    """Register every tool from every MCP client into the shared registry,
    namespacing names as '<server-name>.<tool-name>' to avoid collisions."""
    for client in clients:
        for tool in client.list_tools():
            qualified = f"{client.name}.{tool['name']}"
            inner_name = tool["name"]
            # Capture client and inner_name in default args to avoid late binding
            def handler(args, _c=client, _n=inner_name):
                return _c.call_tool(_n, args)
            registry.register(ToolDefinition(
                name=qualified,
                description=tool["description"],
                input_schema=tool["input_schema"],
                handler=handler,
                is_available=lambda _c=client: _c.is_healthy,
            ))
