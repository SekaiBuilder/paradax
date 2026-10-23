from __future__ import annotations

"""Sentinel-Watch: Daemon 1 — firewall en tiempo real.

Consume del SandboxBus. Para cada ToolRequest:
  1. Verifica vs ToolBroker: ¿tool permitida en este run?
  2. Verifica vs allowed_tools del agente (si se proporciona el mapa de contratos)
  3. Si aprobada: ejecuta via ToolRuntime, responde en reply_queue
  4. Si denegada: responde con ToolResponse(ok=False, blocked_by=...)
  5. Publica el evento al BUS de eventos para el dashboard en vivo

Se lanza como asyncio.Task desde project_runner.py y se cancela al terminar el run.
"""

import asyncio
import logging

from ..core.events import BUS
from ..factory.tool_runtime import ToolRuntime
from .bus import SandboxBus
from .protocol import ToolBlockedError, ToolRequest, ToolResponse
from .tool_broker import ToolBroker

logger = logging.getLogger(__name__)


class SentinelWatch:
    def __init__(
        self,
        bus: SandboxBus,
        broker: ToolBroker,
        runtime: ToolRuntime,
        # Mapa agente_id → set[str] de allowed_tools del contrato.
        # Si es None, se omite la verificación por contrato (más permisivo).
        agent_contracts: dict[str, frozenset[str]] | None = None,
    ) -> None:
        self._bus = bus
        self._broker = broker
        self._runtime = runtime
        self._contracts = agent_contracts or {}

    async def run(self) -> None:
        """Loop principal. Correr como asyncio.Task."""
        logger.info("Sentinel-Watch iniciado para run=%s", self._broker.run_id)
        async for req in self._bus.consume():
            try:
                await self._handle(req)
            except Exception as exc:
                logger.exception("Sentinel-Watch error inesperado en request %s", req.request_id)
                resp = ToolResponse(
                    request_id=req.request_id,
                    ok=False,
                    error=f"error interno del sentinel: {exc}",
                    blocked_by="watch",
                )
                await req.reply_queue.put(resp)
        logger.info("Sentinel-Watch detenido para run=%s", self._broker.run_id)

    async def _handle(self, req: ToolRequest) -> None:
        resp = await self._decide(req)
        BUS.publish("sandbox_tool", {
            "run_id": req.run_id,
            "agent_id": req.agent_id,
            "tool": req.tool_name,
            "ok": resp.ok,
            "blocked_by": resp.blocked_by or None,
            "error": resp.error or None,
        })
        await req.reply_queue.put(resp)

    async def _decide(self, req: ToolRequest) -> ToolResponse:
        # 1. Broker: ¿tool permitida en este tipo de run?
        if not self._broker.is_allowed(req.tool_name):
            logger.warning(
                "BLOCKED by broker | run=%s agent=%s tool=%s",
                req.run_id, req.agent_id, req.tool_name,
            )
            return ToolResponse(
                request_id=req.request_id,
                ok=False,
                blocked_by="broker",
                error=f"'{req.tool_name}' no está en el ToolBroker para task_kind='{self._broker.task_kind}'",
            )

        # 2. Contrato del agente: ¿declaró esta tool en allowed_tools?
        agent_allowed = self._contracts.get(req.agent_id)
        if agent_allowed is not None and req.tool_name not in agent_allowed:
            logger.warning(
                "BLOCKED by contract | run=%s agent=%s tool=%s",
                req.run_id, req.agent_id, req.tool_name,
            )
            return ToolResponse(
                request_id=req.request_id,
                ok=False,
                blocked_by="contract",
                error=f"'{req.tool_name}' no está en allowed_tools del agente '{req.agent_id}'",
            )

        # 3. Runtime: ¿hay callable registrado?
        if not self._runtime.has(req.tool_name):
            return ToolResponse(
                request_id=req.request_id,
                ok=False,
                blocked_by="runtime",
                error=f"'{req.tool_name}' no tiene callable registrado en ToolRuntime",
            )

        # 4. Ejecutar
        try:
            result = await self._runtime.call(req.tool_name, req.args)
            logger.debug(
                "APPROVED | run=%s agent=%s tool=%s",
                req.run_id, req.agent_id, req.tool_name,
            )
            return ToolResponse(request_id=req.request_id, ok=True, result=result)
        except Exception as exc:
            return ToolResponse(
                request_id=req.request_id,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
            )
