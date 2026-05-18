from __future__ import annotations
import asyncio
import threading
from typing import Optional

from avadex.tools.registry import ToolDefinition, ToolRegistry, ToolResult


class MCPClient:
    """Synchronous facade over the async mcp Python SDK (stdio transport).

    Owns a background asyncio loop so the rest of AvaDex can stay sync.
    """

    def __init__(self, name: str, command: str, args: list[str]):
        self.name = name
        self.command = command
        self.args = args
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._session = None  # mcp.ClientSession
        self._exit_stack = None
        self._tools_cache: list[dict] = []

    def start(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from contextlib import AsyncExitStack

        self._loop = asyncio.new_event_loop()

        def _run():
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

        async def _setup():
            self._exit_stack = AsyncExitStack()
            params = StdioServerParameters(command=self.command, args=self.args)
            transport = await self._exit_stack.enter_async_context(stdio_client(params))
            read, write = transport
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
            return ToolResult(content=f"MCP call failed: {exc}", is_error=True)

    def stop(self):
        if not self._loop:
            return
        async def _close():
            if self._exit_stack is not None:
                await self._exit_stack.aclose()
        try:
            fut = asyncio.run_coroutine_threadsafe(_close(), self._loop)
            fut.result(timeout=10)
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
            ))
