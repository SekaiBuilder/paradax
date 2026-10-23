from __future__ import annotations

"""Organigrama de un proyecto: quién manda, quién construye y quién trabaja.

Niveles (de arriba abajo):
  direccion    Project Manager: escucha al usuario y dirige
  constructor  Team Constructor: diseña, fabrica, valida y entrena el equipo
  ejecucion    Orquestador: arma el pipeline y reparte
  deciden      agentes del equipo que deciden (secundarios, ejecutan tools)
  ejecutan     agentes del equipo con una tarea concreta (terciarios)

Aristas: 'mando' (quién encarga a quién) y 'datos' (A escribe lo que B lee).
"""

from typing import Any

from .. import project_runner
from ..agents import REGISTRY
from ..config import DEFAULT_MODEL
from ..core.models import resolve_model
from ..factory import system_agents as sysagents
from ..factory.loader import DYNAMIC
from ..lab.memory import agent_of
from ..training.quarantine import vetoed

LEVELS = [
    ("direccion", "Dirección", "Escucha tu petición y dirige el proyecto"),
    ("constructor", "Team Constructor", "Diseña, fabrica, valida y entrena el equipo"),
    ("ejecucion", "Ejecución", "Arma el pipeline desde los contratos y reparte"),
    ("deciden", "Equipo · deciden", "Agentes que eligen y usan herramientas"),
    ("ejecutan", "Equipo · ejecutan", "Agentes con una tarea concreta y validada"),
]
_CONSTRUCTOR_TEAM = ["team_planner", "skills_definer", "skill_master", "constructor", "auditor", "validador", "entrenador"]
_MEDIA_DECIDE = {"action_planner", "script_writer"}  # los del pipeline de media que usan LLM


def _quarantined() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for model in vetoed():
        out.setdefault(agent_of(model), []).append(model)
    return out


def _model_info(agent_id: str, uses_llm: bool = True) -> dict[str, Any]:
    if not uses_llm:
        return {"model": "determinista", "specialized": False}
    model, student = resolve_model(agent_id, DEFAULT_MODEL)
    return {"model": model, "specialized": student}


def _system_node(agent_id: str, level: str, quarantine: dict[str, list[str]]) -> dict[str, Any]:
    a = sysagents._BY_ID[agent_id]
    return {
        "id": agent_id, "name": a["name"], "role": a["description"], "level": level, "kind": "system",
        "contactable": bool(a.get("contactable")), "quarantined": quarantine.get(agent_id, []),
        **_model_info(agent_id),
    }


def build(project_id: str, project=None) -> dict[str, Any]:
    quarantine = _quarantined()
    nodes = [_system_node("project_manager", "direccion", quarantine)]
    nodes += [_system_node(a, "constructor", quarantine) for a in _CONSTRUCTOR_TEAM]
    nodes.append(_system_node("orquestador", "ejecucion", quarantine))
    system_ids = {n["id"] for n in nodes}
    edges = [{**e, "kind": "mando"} for e in sysagents.SYSTEM_EDGES
             if e["from"] in system_ids and e["to"] in system_ids]

    team: list[dict[str, Any]] = []
    data_edges: list[dict[str, Any]] = []
    if project_id == "media-manager":
        info = {"id": "media-manager", "name": "Media Manager", "goal": "GIFs y reels grabados de páginas reales", "status": "ready"}
        for agent in REGISTRY.values():
            c = agent.contract
            team.append({
                "id": c.id, "name": c.name, "role": c.description, "kind": "team",
                "level": "deciden" if c.id in _MEDIA_DECIDE else "ejecutan",
                "status": "scheduled", "missing": [], "contactable": True,
                "quarantined": quarantine.get(c.id, []), **_model_info(c.id, c.uses_llm),
            })
        writers = {a.contract.writes: a.contract.id for a in REGISTRY.values()}
        for agent in REGISTRY.values():
            for key in agent.contract.reads:
                if key in writers and writers[key] != agent.contract.id:
                    data_edges.append({"from": writers[key], "to": agent.contract.id, "label": key, "kind": "datos"})
    else:
        info = {"id": project.id, "name": project.name, "goal": project.goal, "status": project.status}
        seed = set(project_runner.task_inputs(project, project.goal or project.name).keys())
        plan = project_runner.compute_plan(project, seed)
        for step in plan.get("steps", []):
            agent = DYNAMIC.get(step["agent"])
            uses_llm = bool(getattr(getattr(agent, "contract", None), "uses_llm", True))
            team.append({
                "id": step["agent"], "name": step.get("name") or step["agent"],
                "role": getattr(getattr(agent, "spec", None), "description", "") or "",
                "kind": "team", "level": "deciden" if step.get("tier") == "secondary" else "ejecutan",
                "status": step.get("status", ""), "missing": step.get("missing", []),
                "reads": step.get("reads", []), "writes": step.get("writes", ""),
                "contactable": True, "quarantined": quarantine.get(step["agent"], []),
                **_model_info(step["agent"], uses_llm),
            })
        data_edges = [{**e, "kind": "datos"} for e in plan.get("edges", [])]

    # El Orquestador encarga a quien no recibe datos de otro agente del equipo.
    fed = {e["to"] for e in data_edges}
    edges += [{"from": "orquestador", "to": n["id"], "label": "reparte", "kind": "mando"}
              for n in team if n["id"] not in fed]
    return {
        "project": info,
        "levels": [{"id": lid, "label": label, "description": desc} for lid, label, desc in LEVELS],
        "nodes": nodes + team,
        "edges": edges + data_edges,
    }
