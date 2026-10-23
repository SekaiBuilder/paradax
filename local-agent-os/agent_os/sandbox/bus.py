from __future__ import annotations

"""SandboxBus: canal único entre agentes y Sentinel-Watch.

Los agentes llaman `await SANDBOX_BUS.post(request)` y esperan en
`request.reply_queue`. El Sentinel-Watch consume con `async for req in
SANDBOX_BUS.consume()`.

No es un singleton global — project_runner crea una instancia por run y la
inyecta vía contextvar (ver tool_runtime.py). Esto hace los tests triviales:
solo se instancia un SandboxBus local.
"""

import asyncio
from typing import AsyncIterator

from .protocol import ToolRequest


class SandboxBus:
    def __init__(self, maxsize: int = 256) -> None:
        self._q: asyncio.Queue[ToolRequest | None] = asyncio.Queue(maxsize=maxsize)

    async def post(self, request: ToolRequest) -> None:
        await self._q.put(request)

    async def consume(self) -> AsyncIterator[ToolRequest]:
        while True:
            item = await self._q.get()
            if item is None:
                break
            yield item
            self._q.task_done()

    async def close(self) -> None:
        """Señaliza al consumidor que no hay más items."""
        await self._q.put(None)
