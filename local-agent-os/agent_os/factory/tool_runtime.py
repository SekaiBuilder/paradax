from __future__ import annotations

"""Runtime de herramientas: el mapa de tools EJECUTABLES.

Distinción clave para la seguridad: el `tool_catalog` guarda *metadata* (qué
tools existen, para que el Constructor componga). Este runtime guarda los
*callables* reales. Una tool solo se ejecuta si tiene un callable registrado
AQUÍ. Las tools que el fantasma trae de Claude Code entran al catálogo como
metadata pero NO traen callable — así un agente nunca ejecuta código sin
revisar; como mucho recibe un error de "tool no disponible".

SANDBOX: cuando `SANDBOX_BUS_VAR` está activa (inyectada por project_runner
por run), `call()` NO ejecuta la función directamente sino que manda un
ToolRequest al SandboxBus y espera la respuesta del Sentinel-Watch.
"""

import asyncio
import uuid
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from ..sandbox.bus import SandboxBus

ToolFn = Callable[..., Any] | Callable[..., Awaitable[Any]]

# Contextvars inyectadas por project_runner al inicio de cada run.
# None = modo sin sandbox (tests, runs legacy sin project_runner).
SANDBOX_BUS_VAR: ContextVar["SandboxBus | None"] = ContextVar("sandbox_bus", default=None)
SANDBOX_RUN_ID_VAR: ContextVar[str] = ContextVar("sandbox_run_id", default="")
SANDBOX_AGENT_ID_VAR: ContextVar[str] = ContextVar("sandbox_agent_id", default="")


class ToolRuntime:
    def __init__(self):
        self._fns: dict[str, ToolFn] = {}

    def register(self, name: str, fn: ToolFn) -> None:
        self._fns[name] = fn

    def has(self, name: str) -> bool:
        return name in self._fns

    def names(self) -> list[str]:
        return list(self._fns)

    def without(self, names: set[str]) -> "ToolRuntime":
        """Copia este runtime SIN ciertas tools (p. ej. las de escritura) — para
        que un agente local pueda leer/analizar pero no escribir."""
        rt = ToolRuntime()
        for name, fn in self._fns.items():
            if name not in names:
                rt.register(name, fn)
        return rt

    async def call(self, name: str, args: dict[str, Any]) -> Any:
        bus = SANDBOX_BUS_VAR.get()
        if bus is not None:
            return await self._call_sandboxed(name, args, bus)
        return await self._call_direct(name, args)

    async def _call_sandboxed(self, name: str, args: dict[str, Any], bus: "SandboxBus") -> Any:
        from ..sandbox.protocol import ToolBlockedError, ToolRequest

        req = ToolRequest(
            request_id=uuid.uuid4().hex,
            run_id=SANDBOX_RUN_ID_VAR.get(),
            agent_id=SANDBOX_AGENT_ID_VAR.get(),
            tool_name=name,
            args=args,
        )
        await bus.post(req)
        resp = await req.reply_queue.get()
        if not resp.ok:
            raise ToolBlockedError(name, resp.blocked_by or "watch")
        return resp.result

    async def _call_direct(self, name: str, args: dict[str, Any]) -> Any:
        if name not in self._fns:
            raise KeyError(f"tool sin callable registrado: {name}")
        fn = self._fns[name]
        if asyncio.iscoroutinefunction(fn):
            return await fn(**args)
        return fn(**args)


def _http_get(url: str, max_chars: int = 2000) -> str:
    """GET seguro de una URL pública; devuelve el texto truncado. Usa el lector
    del Investigador: sin direcciones locales/privadas, ni tras redirecciones."""
    from ..research.safe_fetch import fetch_text

    return fetch_text(url, max_chars=max_chars)["text"]


async def _research(question: str) -> dict:
    """El Investigador en modo seguro (SearXNG local). Corre en un hilo: hace red."""
    from ..research.researcher import investigate

    return await asyncio.to_thread(investigate, question, SANDBOX_AGENT_ID_VAR.get(), "segura")


# Runtime por defecto: solo tools seguras y ya implementadas a mano.
DEFAULT_RUNTIME = ToolRuntime()
DEFAULT_RUNTIME.register("http_get", _http_get)
DEFAULT_RUNTIME.register("research", _research)

from . import code_tools as _code_tools  # noqa: E402

DEFAULT_RUNTIME.register("code_list_files", _code_tools.code_list_files)
DEFAULT_RUNTIME.register("code_search", _code_tools.code_search)
DEFAULT_RUNTIME.register("code_read_file", _code_tools.code_read_file)
DEFAULT_RUNTIME.register("code_replace", _code_tools.code_replace)
DEFAULT_RUNTIME.register("code_write_file", _code_tools.code_write_file)
DEFAULT_RUNTIME.register("code_run_pytest", _code_tools.code_run_pytest)
