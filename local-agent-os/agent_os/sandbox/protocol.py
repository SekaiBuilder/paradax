from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field, field_serializer


class ToolRequest:
    """Petición de un agente para ejecutar una tool. No es un BaseModel porque
    contiene una asyncio.Queue (no serializable) para la respuesta."""

    __slots__ = ("request_id", "run_id", "agent_id", "tool_name", "args", "reply_queue")

    def __init__(
        self,
        *,
        request_id: str,
        run_id: str,
        agent_id: str,
        tool_name: str,
        args: dict[str, Any],
    ) -> None:
        self.request_id = request_id
        self.run_id = run_id
        self.agent_id = agent_id
        self.tool_name = tool_name
        self.args = args
        self.reply_queue: asyncio.Queue[ToolResponse] = asyncio.Queue(maxsize=1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "tool_name": self.tool_name,
            "args": self.args,
        }


class ToolResponse(BaseModel):
    request_id: str
    ok: bool
    result: Any = None
    error: str = ""
    blocked_by: str = ""  # "" | "broker" | "contract"


class AuditReport(BaseModel):
    run_id: str
    verdict: str  # "clean" | "violations" | "rollback"
    violations: list[str] = Field(default_factory=list)
    tool_calls: int = 0
    blocked_calls: int = 0
    rollback_sha: str = ""


class ToolBlockedError(RuntimeError):
    """Lanzado cuando Sentinel-Watch bloquea una tool call."""

    def __init__(self, tool_name: str, blocked_by: str) -> None:
        self.tool_name = tool_name
        self.blocked_by = blocked_by
        super().__init__(f"tool bloqueada por '{blocked_by}': {tool_name}")
