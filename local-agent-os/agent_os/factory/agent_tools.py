from __future__ import annotations

"""Tools que los agentes de sistema CONTACTABLES pueden ejecutar durante el chat.

A diferencia de las tools de run (factory/tool_runtime.py, que operan dentro del
sandbox de un pipeline), estas son acciones de administración que el usuario pide
conversando — "publica el reel a las 3am todos los días" → crear un smart
schedule. El endpoint de chat corre estas tools en un bucle acotado (mismo patrón
JSON que ToolExecutingAgent) ANTES de redactar la respuesta, y luego el agente
confirma en lenguaje natural lo que hizo.

Todas las importaciones pesadas van dentro de las funciones para evitar ciclos
de importación (este módulo vive en factory/, y las tools tocan project_runner y
automation/, que a su vez importan factory).
"""

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from ..config import FAST_MODEL
from ..ollama import chat_json


@dataclass
class AgentTool:
    name: str
    description: str
    fn: Callable[..., Any]
    params: dict[str, str] = field(default_factory=dict)  # nombre → descripción (para el prompt)


# ── Acceso al store vivo ──────────────────────────────────────────────────────

def _store():
    """Store de proyectos COMPARTIDO con el server (misma instancia en memoria).

    Import perezoso: en tiempo de llamada el server ya está cargado, así que las
    tools ven — y modifican — los mismos proyectos que la app. Fallback a un store
    de disco solo si se usan fuera del server (scripts sueltos)."""
    try:
        from ..server import PM
        return PM.store
    except Exception:
        from .project import ProjectStore
        return ProjectStore()


# ── Callables (acciones reales) ───────────────────────────────────────────────

def _list_projects() -> list[dict[str, Any]]:
    return [
        {
            "id": p.id,
            "name": p.name,
            "goal": (p.goal or "")[:120],
            "agentes": len(p.agents),
            "listo": bool(p.agents),
        }
        for p in _store().all()
    ]


def _create_project(name: str, goal: str = "") -> dict[str, Any]:
    if not name or not name.strip():
        return {"ok": False, "error": "name es obligatorio"}
    p = _store().create(name.strip(), goal=(goal or "").strip())
    return {
        "ok": True,
        "project_id": p.id,
        "name": p.name,
        "goal": p.goal,
        "siguiente": "el proyecto está vacío; usa build_project_team para construir su equipo",
    }


def _build_project_team(project_id: str) -> dict[str, Any]:
    import asyncio

    try:
        from ..server import PM
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"constructor no disponible fuera del server: {exc}"}

    project = PM.store.get(project_id)
    if project is None:
        return {"ok": False, "error": f"no existe el proyecto '{project_id}' — usa list_projects o create_project"}

    async def _run():
        try:
            await PM.build_team(project)
        except Exception:
            return  # project_build_finished(failed) ya informa por el BUS
        # Modo automático: el pipeline corre solo al quedar el equipo listo.
        p = PM.store.get(project_id)
        if p and p.auto_run and p.agents:
            try:
                from ..project_runner import run_project
                await run_project(p, model=FAST_MODEL)
            except Exception:
                pass

    asyncio.create_task(_run())
    nota = "reconstruye el equipo" if project.agents else "construcción del equipo lanzada"
    return {
        "ok": True,
        "project_id": project_id,
        "lanzado": True,
        "nota": f"{nota} en segundo plano; el progreso se ve en el panel del proyecto",
    }


def _create_smart_schedule(
    project_id: str,
    deadline_time: str,
    days_of_month: Any,
    label: str = "",
) -> dict[str, Any]:
    from ..automation.duration_tracker import DurationTracker
    from ..automation.smart_scheduler import create_schedule, schedule_with_estimate
    from ..project_runner import _detect_task_kind

    project = _store().get(project_id)
    if project is None:
        return {"ok": False, "error": f"no existe el proyecto '{project_id}' — usa list_projects primero"}

    try:
        days = [int(d) for d in days_of_month] if isinstance(days_of_month, (list, tuple)) else []
    except (TypeError, ValueError):
        days = []
    days = [d for d in days if 1 <= d <= 31]
    if not days:
        return {"ok": False, "error": "days_of_month debe ser una lista de días del mes (1-31), ej [1,15]"}

    # El task_kind lo decide el proyecto, no el modelo: así el bucket de
    # duraciones coincide con el que registra run_project.
    task_kind = _detect_task_kind(project)
    s = create_schedule(
        project_id=project_id,
        deadline_time=deadline_time.strip(),
        days_of_month=days,
        task_kind=task_kind,
        label=label or "",
    )
    enriched = schedule_with_estimate(s, DurationTracker())
    return {
        "ok": True,
        "schedule_id": s["id"],
        "project": project.name,
        "deadline_time": s["deadline_time"],
        "days_of_month": s["days_of_month"],
        "arranca_estimado": enriched.get("_start_time"),
        "duracion_estimada_min": enriched.get("_estimated_minutes"),
    }


def _list_smart_schedules(project_id: str = "") -> list[dict[str, Any]]:
    from ..automation.smart_scheduler import all_schedules
    items = all_schedules()
    if project_id:
        items = [s for s in items if s["project_id"] == project_id]
    return [
        {
            "schedule_id": s["id"],
            "project_id": s["project_id"],
            "deadline_time": s["deadline_time"],
            "days_of_month": s["days_of_month"],
            "enabled": s["enabled"],
        }
        for s in items
    ]


def _delete_smart_schedule(schedule_id: str) -> dict[str, Any]:
    from ..automation.smart_scheduler import delete_schedule
    return {"ok": delete_schedule(schedule_id), "schedule_id": schedule_id}


# ── Registro: agente → tools ──────────────────────────────────────────────────

AGENT_TOOLS: dict[str, list[AgentTool]] = {
    "project_manager": [
        AgentTool(
            "list_projects",
            "Lista los proyectos existentes (id, nombre, objetivo, nº de agentes, si "
            "ya está listo). Úsala para saber qué hay antes de crear o construir.",
            _list_projects,
        ),
        AgentTool(
            "create_project",
            "Crea un proyecto nuevo (vacío, sin equipo todavía). Devuelve su project_id.",
            _create_project,
            {
                "name": "nombre corto del proyecto",
                "goal": "objetivo en una frase (qué debe lograr el proyecto)",
            },
        ),
        AgentTool(
            "build_project_team",
            "Lanza la construcción del equipo especializado para un proyecto (el Team "
            "Constructor fabrica y valida sus agentes). Corre en segundo plano.",
            _build_project_team,
            {"project_id": "id EXACTO del proyecto (de list_projects o create_project)"},
        ),
    ],
    "automation_manager": [
        AgentTool(
            "list_projects",
            "Lista los proyectos existentes (id, nombre, objetivo). Úsala para "
            "encontrar el project_id correcto a partir de lo que menciona el usuario.",
            _list_projects,
        ),
        AgentTool(
            "create_smart_schedule",
            "Crea una programación inteligente: el proyecto arranca con antelación "
            "para TERMINAR antes de deadline_time.",
            _create_smart_schedule,
            {
                "project_id": "id EXACTO del proyecto (obtenido de list_projects)",
                "deadline_time": "hora límite de finalización 'HH:MM' (24h)",
                "days_of_month": "lista de días del mes [1-31], ej [1,15] o [1,2,...,31] para diario",
                "label": "etiqueta opcional",
            },
        ),
        AgentTool(
            "list_smart_schedules",
            "Lista las programaciones existentes (opcionalmente filtradas por project_id).",
            _list_smart_schedules,
            {"project_id": "opcional; filtra por proyecto"},
        ),
        AgentTool(
            "delete_smart_schedule",
            "Elimina una programación por su schedule_id.",
            _delete_smart_schedule,
            {"schedule_id": "id de la programación a borrar"},
        ),
    ],
}


def has_tools(agent_id: str) -> bool:
    return agent_id in AGENT_TOOLS


def _catalog(tools: list[AgentTool]) -> str:
    lines = []
    for t in tools:
        args = ", ".join(t.params) if t.params else ""
        lines.append(f"  - {t.name}({args}): {t.description}")
        for p, d in t.params.items():
            lines.append(f"      · {p}: {d}")
    return "\n".join(lines)


async def run_tool_loop(
    agent_id: str,
    model: str,
    persona: str,
    history: list[dict],
    max_steps: int = 5,
) -> list[str]:
    """Deja que el agente ejecute sus tools antes de responder. Devuelve un
    transcript legible de las acciones ejecutadas para que la respuesta final las
    confirme. Si no hace falta ninguna acción, devuelve lista vacía."""
    tools = AGENT_TOOLS.get(agent_id, [])
    if not tools:
        return []
    by_name = {t.name: t for t in tools}

    system = (
        persona
        + "\n\n--- Protocolo de herramientas ---\n"
        + "Puedes ejecutar acciones reales. Herramientas disponibles:\n"
        + _catalog(tools)
        + "\n\nEn cada turno responde SOLO un JSON, una de dos formas:\n"
        + '  1) ejecutar una tool: {"tool": "<nombre>", "args": {...}}\n'
        + '  2) no hace falta (ninguna acción o ya terminaste): {"done": true}\n'
        + "Reglas: para crear/borrar una programación necesitas el id EXACTO; si no lo "
        + "tienes, primero llama list_projects o list_smart_schedules. Nunca inventes ids. "
        + "Ejecuta solo lo que el usuario pide de forma clara. No escribas nada fuera del JSON."
    )
    convo = "\n".join(f'{m["role"]}: {m["content"]}' for m in history[-8:])

    transcript: list[str] = []
    for _ in range(max_steps):
        user = "Conversación:\n" + convo
        if transcript:
            user += "\n\nResultados de tools hasta ahora:\n" + "\n".join(transcript)
        user += '\n\n¿Qué tool ejecutas ahora, o {"done": true}?'
        try:
            # Las decisiones de tools son JSON cortos: el modelo rápido las
            # resuelve en segundos; la redacción final sí usa el del chat.
            raw = await chat_json(FAST_MODEL, system, user)
        except Exception as exc:  # noqa: BLE001 — si el modelo falla, seguimos sin tools
            transcript.append(f"(no se pudo decidir acción: {exc})")
            break

        if not isinstance(raw, dict) or "tool" not in raw:
            break  # {"done": true} o cualquier cosa que no sea tool → fin

        name = raw.get("tool")
        args = raw.get("args") or {}
        if name not in by_name:
            transcript.append(f"tool '{name}' no existe")
            continue
        try:
            result = by_name[name].fn(**(args if isinstance(args, dict) else {}))
        except TypeError as exc:
            transcript.append(f"{name}: argumentos inválidos ({exc})")
            continue
        except Exception as exc:  # noqa: BLE001
            transcript.append(f"{name}: ERROR {exc}")
            continue
        transcript.append(
            f"{name}({json.dumps(args, ensure_ascii=False)}) -> "
            f"{json.dumps(result, ensure_ascii=False)[:600]}"
        )
    return transcript
