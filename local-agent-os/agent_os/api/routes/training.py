from __future__ import annotations

"""Entrenamiento: estado de alumnos, Entrenador, destilación y especialización."""

import asyncio
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...config import DEFAULT_MODEL
from ...factory.entrenador import Entrenador
from ...factory.loader import DYNAMIC

router = APIRouter()


@router.get("/api/training/status")
def training_status(ids: str | None = None):
    """Mini resumen de la situación de cada agente (la ⓘ junto a su nombre):
    alumno, valores, racha hacia la promoción o motivo de cuarentena."""
    from ...factory.system_agents import SYSTEM_AGENTS
    from ...training.morning_report import agent_status
    wanted = ids.split(",") if ids else [a["id"] for a in SYSTEM_AGENTS]
    out = {}
    for aid in wanted:
        try:
            out[aid] = agent_status(aid)
        except Exception as exc:  # noqa: BLE001 — una ⓘ rota no debe tumbar la lista
            out[aid] = {"level": "nada", "text": f"sin datos ({type(exc).__name__})"}
    return out


class RefineRequest(BaseModel):
    focus: str = ""
    material: str = ""   # URL o ruta a PDF/archivo de texto (opcional)


@router.post("/api/factory/agents/{agent_id}/train")
async def factory_agent_train(agent_id: str, req: RefineRequest):
    """Envía el agente al Entrenador para afinar sus skills sobre algo específico."""
    agent = DYNAMIC.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agente no encontrado")
    try:
        return await Entrenador().refine(agent, focus=req.focus, material_source=req.material or None)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class DistillRequest(BaseModel):
    agent_id: str
    inputs: list[dict] = []          # si vacío, usa los inputs de los evals del agente
    version: str = "v1"
    min_examples: int = 100


@router.post("/api/factory/distill")
async def factory_distill(req: DistillRequest):
    from ...factory.distiller import AgentDistiller
    agent = DYNAMIC.get(req.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"agente construido no encontrado: {req.agent_id}")
    inputs = req.inputs or [ev.get("input", {}) for ev in agent.spec.evals]
    report = await AgentDistiller().distill(agent, inputs, version=req.version, min_examples=req.min_examples)
    return report.model_dump()


# ── Especialización de agentes: prompt genérico → modelo propio ───────────────
# Circuito universal maestro→alumno que aprende de los runs REALES verificados.

@router.get("/api/factory/agents/{agent_id}/specialize")
def specialize_readiness(agent_id: str):
    """¿Cuántos ejemplos verificados tiene el agente y si ya puede entrenar?"""
    from ...factory import distill_agent
    if DYNAMIC.get(agent_id) is None:
        raise HTTPException(status_code=404, detail="agente no encontrado")
    from ...factory.entrenador import Entrenador
    st = distill_agent.readiness(agent_id)
    st["current_model"] = Entrenador().status(agent_id).get("model")
    st["is_specialist"] = agent_id in Entrenador().models_map()
    return st


class SpecializeRequest(BaseModel):
    version: str = "v1"
    force: bool = False
    promote: bool = True
    iters: int | None = None   # acorta el LoRA (solo pruebas de humo)


@router.post("/api/factory/agents/{agent_id}/specialize")
async def specialize_agent(agent_id: str, req: SpecializeRequest):
    """Destila un modelo especialista para el agente desde sus runs verificados:
    cosecha → dataset → fine-tune LoRA → (promociona). Bloqueante: minutos."""
    from ...factory import distill_agent
    if DYNAMIC.get(agent_id) is None:
        raise HTTPException(status_code=404, detail="agente no encontrado")

    path, n = distill_agent.build_dataset(agent_id)
    ready = distill_agent.readiness(agent_id)
    if not ready["ready"] and not req.force:
        return {"ok": False, "stage": "dataset", "examples": n,
                "detail": f"solo {n} ejemplos verificados; hacen falta {ready['min_examples']}. "
                          "Ejecuta el proyecto más veces (o usa force para una prueba)."}

    # El entrenamiento es pesado: lo corremos en un hilo para no bloquear el loop.
    result = await asyncio.to_thread(
        distill_agent.train, agent_id, req.version, force=req.force, iters=req.iters
    )
    if result.get("ok") and req.promote:
        distill_agent.promote(agent_id, result["published"])
        result["promoted"] = True
    result["examples"] = n
    return result


class MetabolizeRequest(BaseModel):
    version: str = "v2"
    holdout_k: int = 15
    min_gain: float = 0.0


@router.post("/api/factory/agents/{agent_id}/metabolize")
async def metabolize_agent(agent_id: str, req: MetabolizeRequest):
    """Ciclo de auto-mejora CON eval gate: entrena un candidato y lo promueve
    SOLO si no degrada contra el modelo actual (protección anti-deriva)."""
    from ...factory import distill_agent
    if DYNAMIC.get(agent_id) is None:
        raise HTTPException(status_code=404, detail="agente no encontrado")
    return await distill_agent.metabolize(
        agent_id, req.version, holdout_k=req.holdout_k, min_gain=req.min_gain
    )


@router.get("/api/factory/entrenador")
def factory_entrenador():
    ent = Entrenador()
    return {"roster": ent.roster(), "collaborators": ent.collaborators()}


class IngestRequest(BaseModel):
    source: str   # URL, o ruta a PDF / archivo de texto


@router.post("/api/factory/entrenador/ingest")
async def factory_entrenador_ingest(req: IngestRequest):
    """El Entrenador despierta al colaborador adecuado para leer material.
    El usuario no habla con los colaboradores; se los pide al Entrenador."""
    try:
        mat = await Entrenador().ingest_material(req.source)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return mat.model_dump()


@router.get("/api/factory/entrenador/queue")
def factory_entrenador_queue():
    return {"queue": Entrenador().training_queue()}


@router.post("/api/factory/entrenador/queue/{agent_id}/run")
async def factory_entrenador_run(agent_id: str, model: str = DEFAULT_MODEL):
    """Dispara la destilación real para un agente encolado."""
    agent = DYNAMIC.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agente no encontrado")
    try:
        return await Entrenador().run_training(agent, model=model)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/api/factory/entrenador/queue/{agent_id}")
def factory_entrenador_dequeue(agent_id: str):
    return {"removed": Entrenador().dequeue(agent_id)}


@router.get("/api/training/exam")
def training_exam(limit: int = 10):
    """Últimos exámenes graduados (nivel automático + revisión con Claude)."""
    from ...training.graded_exam import RESULTS, REVIEW_FROM
    history = json.loads(RESULTS.read_text(encoding="utf-8")) if RESULTS.exists() else []
    return {"review_from": REVIEW_FROM, "exams": list(reversed(history[-limit:]))}
