from __future__ import annotations

"""Estado compartido del servidor: fábrica, Project Manager, historiales de
chat, tareas en vuelo y helpers de jerarquía. Los routers importan de aquí;
nadie más crea instancias propias."""

import asyncio
import re

from fastapi import HTTPException
from pydantic import BaseModel

from .. import project_runner
from ..agents import REGISTRY
from ..config import DATA_DIR, DEFAULT_MODEL
from ..factory.factory import AgentFactory
from ..factory.loader import DYNAMIC
from ..factory.project_manager import ProjectManager
from ..factory.spec import effective_tier

# Tareas en vuelo: guardamos la referencia para que el GC no las cancele.
running_tasks: set[asyncio.Task] = set()
_running_tasks = running_tasks


def spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    running_tasks.add(task)
    task.add_done_callback(running_tasks.discard)
    return task


HIERARCHY_FILE = DATA_DIR / "hierarchy.json"

# Posiciones que dibujan el flujo real del pipeline en el grafo.
_HIERARCHY_LAYOUT = {
    "orchestrator":     {"x": 300, "y": 40,  "color": "#7c3aed"},
    "page_inspector":   {"x": 60,  "y": 210, "color": "#059669"},
    "action_planner":   {"x": 300, "y": 210, "color": "#2563eb"},
    "script_writer":    {"x": 540, "y": 210, "color": "#db2777"},
    "browser_recorder": {"x": 60,  "y": 380, "color": "#d97706"},
    "verifier":         {"x": 300, "y": 380, "color": "#dc2626"},
    "video_builder":    {"x": 540, "y": 380, "color": "#0891b2"},
}

DEFAULT_HIERARCHY = {
    "agents": [
        {
            "id": "orchestrator",
            "name": "Orchestrator",
            "role": "Solo reparte y verifica: no hace el trabajo",
            **_HIERARCHY_LAYOUT["orchestrator"],
        },
        *[
            {
                "id": agent.contract.id,
                "name": agent.contract.name,
                "role": agent.contract.description,
                **_HIERARCHY_LAYOUT.get(agent.contract.id, {"x": 100, "y": 100, "color": "#2563eb"}),
            }
            for agent in REGISTRY.values()
        ],
    ],
    "edges": [
        {"from": "orchestrator", "to": "page_inspector", "label": "url"},
        {"from": "page_inspector", "to": "action_planner", "label": "selectores"},
        {"from": "orchestrator", "to": "script_writer", "label": "pedido"},
        {"from": "action_planner", "to": "browser_recorder", "label": "plan"},
        {"from": "browser_recorder", "to": "verifier", "label": "gif"},
        {"from": "verifier", "to": "browser_recorder", "label": "repara"},
        {"from": "verifier", "to": "video_builder", "label": "gif ok"},
        {"from": "script_writer", "to": "video_builder", "label": "guion"},
    ],
}




chat_histories: dict[str, list[dict]] = {}


class ChatRequest(BaseModel):
    message: str
    model: str = DEFAULT_MODEL
    lang: str = "es"   # idioma de la interfaz: el agente responde en él


def in_language(system: str, lang: str) -> str:
    """Los prompts están en español; si la interfaz está en inglés, la respuesta también."""
    if lang != "en":
        return system
    # Una frase corta no basta: con el resto del prompt en español, el modelo sigue en español.
    return system + ("\n\nIMPORTANT: the user writes in English. Your whole answer must be in English, "
                     "even though these instructions are in Spanish.")


FACTORY = AgentFactory(registry=DYNAMIC)
PM = ProjectManager(factory=FACTORY)
project_chat_histories: dict[str, list[dict]] = {}

_TASK_REQUEST_RE = re.compile(
    r"\b("
    r"haz|hacer|hazme|necesito que|quiero que|ejecuta|ejecutar|trabaja|trabajar|"
    r"agrega|agregar|añade|anade|implementar?|implementa|reprograma|programa|"
    r"actualiza|actualizar|mejora|mejorar|cambia|cambiar|arregla|arreglar|"
    r"corrige|corregir|busca|buscar|genera|generar|prepara|preparar|"
    r"crea|crear|escribe|escribir|redacta|redactar|publica|publicar|"
    r"elimina|eliminar|borra|borrar|quita|quitar|dise[ñn]a|dise[ñn]ar|"
    r"optimiza|optimizar|refactoriza|refactorizar|analiza|analizar|dame|"
    r"funcionalidad|feature|bug|fix|tarea"
    r")\b",
    re.IGNORECASE,
)


def _is_task_request(message: str) -> bool:
    return bool(_TASK_REQUEST_RE.search(message))


_CODE_WRITE_TOOLS = {"code_replace", "code_write_file"}


def _project_edits_code(project) -> bool:
    """¿Algún agente del proyecto MODIFICA código (tiene tools de escritura)?
    Esos runs no se auto-lanzan desde el chat: exigen confirmación explícita."""
    for aid in project.agents:
        agent = DYNAMIC.get(aid)
        if agent and (_CODE_WRITE_TOOLS & set(getattr(agent.contract, "allowed_tools", ()))):
            return True
    return False


def _task_status_from_result(result: dict) -> str:
    status = result.get("status")
    if status in {"completed", "blocked", "failed"}:
        return status
    return project_runner.result_status(result)


def _launch_project_task(project_id: str, message: str, model: str) -> dict:
    project = PM.store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="proyecto no encontrado")
    task = project.add_task(message)
    project.update_task(task.id, status="running")
    project.note(f"PM: tarea creada desde el chat ({task.id}): {message[:160]}")
    PM.store.save(project)
    seed = project_runner.task_inputs(project, message)

    async def _run_task():
        try:
            current = PM.store.get(project_id)
            if not current:
                return
            result = await project_runner.run_project(
                current,
                model=model,
                request=message,
                seed_override=seed,
            )
            latest = PM.store.get(project_id)
            if latest:
                updated = latest.update_task(
                    task.id,
                    status=_task_status_from_result(result),
                    run_id=result.get("run_id", ""),
                    result=result,
                )
                latest.note(f"PM: tarea {task.id} terminó como {updated.status if updated else 'desconocida'}")
                PM.store.save(latest)
        except Exception as exc:  # noqa: BLE001
            latest = PM.store.get(project_id)
            if latest:
                latest.update_task(task.id, status="failed", error=str(exc)[:500])
                latest.note(f"PM: tarea {task.id} falló: {str(exc)[:160]}")
                PM.store.save(latest)

    spawn(_run_task())
    return {"task": task.model_dump(), "seed_keys": sorted(seed)}



# ── Hierarchy ────────────────────────────────────────────────────────────────

def _agent_project(agent) -> str:
    spec = getattr(agent, "spec", None)
    return getattr(spec, "project", "") if spec else ""


# Color por jerarquía: secundario (decide) azul · terciario (específico) teal.
_TIER_COLOR = {"secondary": "#2563eb", "tertiary": "#14b8a6"}


def _agent_tier(agent) -> str:
    spec = getattr(agent, "spec", None)
    return effective_tier(spec) if spec else "tertiary"


def _project_visible(proj: str, project_filter: str | None) -> bool:
    """Un grafo, filtrable por proyecto. Sin filtro: solo agentes SIN proyecto
    (los de proyecto viven dentro de su proyecto). 'all': todos. '<id>': los de
    ese proyecto."""
    if project_filter == "all":
        return True
    if project_filter:
        return proj == project_filter
    return not proj


def _project_name(pid: str) -> str:
    p = PM.store.get(pid)
    return p.name if p else pid


def _with_dynamic_nodes(base: dict, project_filter: str | None = None) -> dict:
    """Inyecta los agentes construidos VISIBLES, CONECTADOS a su origen: los de
    un proyecto cuelgan de un nodo del proyecto; los sueltos, del Constructor.
    Sin esto los agentes nuevos aparecían aislados (nodos sin aristas)."""
    merged = {"agents": list(base.get("agents", [])), "edges": list(base.get("edges", []))}
    present = {a.get("id") for a in merged["agents"]}

    visible = [a for a in DYNAMIC.all()
               if a.contract.id not in present and _project_visible(_agent_project(a), project_filter)]

    # agrupa por origen (proyecto o "suelto") para darle un nodo raíz a cada cluster
    groups: dict[str, list] = {}
    for agent in visible:
        groups.setdefault(_agent_project(agent) or "__adhoc__", []).append(agent)

    # Si no hay pipeline de fondo (filtrando un proyecto), el clúster arranca arriba.
    root_y = 470 if merged["agents"] else 70
    for col, (key, agents) in enumerate(groups.items()):
        root_id = f"origin::{key}"
        root_x = 80 + col * 230
        merged["agents"].append({
            "id": root_id,
            "name": "Constructor" if key == "__adhoc__" else _project_name(key),
            "role": "agentes sueltos" if key == "__adhoc__" else "proyecto",
            "x": root_x, "y": root_y, "color": "#7c3aed", "origin": True,
        })
        for k, agent in enumerate(agents):
            tier = _agent_tier(agent)
            merged["agents"].append({
                "id": agent.contract.id,
                "name": agent.contract.name,
                "role": agent.contract.description,
                "x": root_x, "y": root_y + 90 + k * 72,
                "color": _TIER_COLOR.get(tier, "#14b8a6"),
                "constructed": True,
                "project": _agent_project(agent),
                "tier": tier,
            })
            merged["edges"].append({
                "from": root_id, "to": agent.contract.id,
                "label": "construido" if key == "__adhoc__" else "equipo",
            })
    return merged


