from __future__ import annotations

"""ToolBroker: define qué herramientas están disponibles para un run concreto.

Se crea UNA vez por run en project_runner.py basándose en el tipo de tarea
(task_kind). No usa LLM — la decisión es un mapping declarativo.

Los agentes NO ven el broker directamente: Sentinel-Watch lo consulta cuando
intercepta un ToolRequest.
"""

from dataclasses import dataclass, field


# Mapping task_kind → set de tools permitidas en ese tipo de run.
# Sirve como lista explícita: si una tool no está aquí, Sentinel-Watch
# la bloqueará aunque el agente la declare en su contrato.
_TOOL_SETS: dict[str, frozenset[str]] = {
    "media": frozenset({
        "http_get",
        "record_page_gif",
        "make_reel",
        "verify_media",
        "write_actions",
    }),
    "code": frozenset({
        "code_list_files",
        "code_search",
        "code_read_file",
        "code_replace",
        "code_write_file",
        "code_run_pytest",
    }),
    "jobsearch": frozenset({
        "http_get",
        "research",
    }),
    # Wildcard para runs internos del sistema (factory, constructor…).
    # Las tools se declaran explícitamente en el contrato del agente;
    # el broker no añade restricciones adicionales.
    "system": frozenset({
        "http_get",
        "research",
        "code_list_files",
        "code_search",
        "code_read_file",
        "code_replace",
        "code_write_file",
        "code_run_pytest",
    }),
}

# Ninguna tool — para runs sin herramientas (solo LLM).
_EMPTY: frozenset[str] = frozenset()


@dataclass
class ToolBroker:
    run_id: str
    task_kind: str
    _allowed: frozenset[str] = field(repr=False)

    def is_allowed(self, tool_name: str) -> bool:
        return tool_name in self._allowed

    @property
    def allowed_tools(self) -> frozenset[str]:
        return self._allowed

    @classmethod
    def for_task(cls, run_id: str, task_kind: str) -> "ToolBroker":
        allowed = _TOOL_SETS.get(task_kind, _EMPTY)
        return cls(run_id=run_id, task_kind=task_kind, _allowed=allowed)

    @classmethod
    def unrestricted(cls, run_id: str) -> "ToolBroker":
        """Broker sin restricciones — solo para Ghost y Sentinelas."""
        all_tools: frozenset[str] = frozenset().union(*_TOOL_SETS.values())
        return cls(run_id=run_id, task_kind="unrestricted", _allowed=all_tools)
