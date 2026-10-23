from __future__ import annotations

"""Fábrica (Team Constructor): construir agentes, fichas, skills y peticiones del fantasma."""


from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...config import DEFAULT_MODEL
from ...factory.entrenador import Entrenador
from ...factory.loader import DYNAMIC
from ...factory.spec import effective_tier
from ..state import FACTORY

router = APIRouter()


# ── Fábrica de agentes ─────────────────────────────────────────────────────────

class BuildRequest(BaseModel):
    request: str
    model: str = DEFAULT_MODEL
    escalate: bool = False    # llamar al fantasma (Claude Code) si falla
    run_evals: bool = False


@router.post("/api/factory/build")
async def factory_build(req: BuildRequest):
    report = await FACTORY.build(req.request, model=req.model, escalate=req.escalate, run_evals=req.run_evals)
    return report.model_dump()


@router.get("/api/factory/skills")
def factory_skills():
    return {"skills": FACTORY.skills_catalog(), "stats": FACTORY.skills.stats()}


@router.get("/api/factory/specs")
def factory_specs():
    return {"specs": [a.spec.model_dump() for a in DYNAMIC.all()]}


@router.get("/api/factory/agents/{agent_id}")
def factory_agent_detail(agent_id: str):
    """Ficha de un agente construido: contrato + skills resueltas + estado de modelo."""
    agent = DYNAMIC.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agente no encontrado")
    spec = agent.spec
    resolved = []
    for sid in spec.skills:
        s = FACTORY.skills.get(sid)
        resolved.append({"id": sid, "name": s.name if s else sid,
                         "description": s.description if s else "", "missing": s is None})
    return {**spec.model_dump(), "tier": effective_tier(spec), "resolved_skills": resolved, "model_status": Entrenador().status(agent_id)}


@router.delete("/api/factory/agents/{agent_id}")
def factory_agent_delete(agent_id: str):
    """Elimina un agente construido del mapa general."""
    return {"removed": DYNAMIC.unregister(agent_id)}


class AgentEdit(BaseModel):
    skills: list[str] | None = None
    tier: str | None = None


@router.post("/api/factory/agents/{agent_id}/edit")
def factory_agent_edit(agent_id: str, req: AgentEdit):
    """Edita skills y/o tier de un agente construido (Skill Master + taxonomía).
    'secondary' lo vuelve ejecutor de herramientas (decide); 'tertiary' lo deja
    en generación validada (específico). Recompila y re-persiste el spec."""
    agent = DYNAMIC.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agente no encontrado")
    spec = agent.spec
    if req.skills is not None:
        spec.skills = req.skills
    if req.tier is not None:
        if req.tier not in ("secondary", "tertiary"):
            raise HTTPException(status_code=400, detail="tier debe ser 'secondary' o 'tertiary'")
        spec.tier = req.tier
        spec.uses_tools = (req.tier == "secondary")
    try:
        DYNAMIC.register(spec)  # recompila (valida) + re-persiste el JSON
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"el spec no compila: {exc}") from exc
    return factory_agent_detail(agent_id)


@router.get("/api/factory/ghost/pending")
def factory_ghost_pending():
    return {"pending": [p.model_dump() for p in FACTORY.ghost.pending()]}


class GhostAction(BaseModel):
    id: str


@router.post("/api/factory/ghost/approve")
def factory_ghost_approve(action: GhostAction):
    try:
        skill = FACTORY.ghost.approve(action.id, FACTORY.skills)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"approved": skill.id, "skill": skill.model_dump()}


@router.post("/api/factory/ghost/reject")
def factory_ghost_reject(action: GhostAction):
    return {"rejected": FACTORY.ghost.reject(action.id)}


@router.get("/api/factory/ghost/pending_tools")
def factory_ghost_pending_tools():
    return {"pending_tools": [p.model_dump() for p in FACTORY.ghost.pending_tools()]}


@router.post("/api/factory/ghost/approve_tool")
def factory_ghost_approve_tool(action: GhostAction):
    """Aprueba una tool propuesta: escribe el código para revisión humana y
    registra su metadata. NO ejecuta nada."""
    try:
        return FACTORY.ghost.approve_tool(action.id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
