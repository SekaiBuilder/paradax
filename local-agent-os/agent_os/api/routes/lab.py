from __future__ import annotations

"""Laboratorio: cuarentena, archivo de campo y entrevistas con memoria."""

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...lab import archive, interview, memory
from ...training import quarantine

router = APIRouter(prefix="/api/lab")


def _case_summary(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": c.get("id"), "night": c.get("night"), "ts": c.get("ts"),
        "agent": c.get("agent"), "model": c.get("model"),
        "category": c.get("category"), "category_label": quarantine.CATEGORY_LABEL.get(c.get("category", ""), c.get("category", "")),
        "severity": c.get("severity"), "signals": c.get("signals", []),
        "task": memory.need(c.get("user", ""))[:300],
    }


@router.get("/overview")
def overview():
    """Modelos en cuarentena (vetados o con casos), con su resumen."""
    vetoed = quarantine.vetoed()
    reassigned = quarantine.reassigned()
    deleted = quarantine.deleted()
    by_model: dict[str, list[dict[str, Any]]] = {}
    for c in memory.all_cases():
        by_model.setdefault(c["model"], []).append(c)
    models = []
    for model in sorted(set(vetoed) | set(by_model)):
        cases = by_model.get(model, [])
        mem = memory.load(model)
        models.append({
            "model": model,
            "agent": memory.agent_of(model),
            "version": model.split(":")[-1] if ":" in model else "",
            "vetoed": model in vetoed,
            "deleted": model in deleted,
            "reason": vetoed.get(model, ""),
            "reassigned": reassigned.get(model, ""),
            "cases": len(cases),
            "categories": sorted({c.get("category", "") for c in cases}),
            "last_ts": max((c.get("ts", 0) for c in cases), default=0),
            "sessions": len(mem["sessions"]),
            "turns": sum(len(s["turns"]) for s in mem["sessions"]),
        })
    models.sort(key=lambda m: (m["deleted"], not m["vetoed"], -m["last_ts"]))
    return {"models": models, "docs": len(archive.list_docs())}


@router.get("/cases")
def cases(model: str):
    return {"cases": [_case_summary(c) for c in reversed(memory.cases_for(model))]}


@router.get("/cases/{cid}")
def case_detail(cid: str):
    case = next((c for c in memory.all_cases() if c.get("id") == cid), None)
    if case is None:
        raise HTTPException(status_code=404, detail="caso no encontrado")
    return {**_case_summary(case), "user": case.get("user", ""), "raw": case.get("raw"),
            "teacher_raw": case.get("teacher_raw")}


@router.get("/memory")
def memory_view(model: str, session: str = "preview"):
    """La memoria tal cual la recibe el modelo: transparencia total."""
    if model not in memory.quarantined_models():
        raise HTTPException(status_code=404, detail="ese modelo no está en cuarentena")
    data = memory.load(model)
    return {"model": model, "sessions": data["sessions"], "system_prompt": memory.build_system(model, session)}


class InterviewRequest(BaseModel):
    model: str
    session_id: str
    message: str


@router.post("/interview")
async def interview_chat(req: InterviewRequest):
    try:
        interview.check(req.model, req.session_id, req.message)
    except interview.InterviewError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def generate():
        try:
            async for chunk in interview.reply(req.model, req.session_id, req.message):
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as exc:  # noqa: BLE001 — el error llega a la UI, no tumba el stream
            yield f"data: {json.dumps({'error': str(exc)[:300]}, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class ReleaseRequest(BaseModel):
    model: str


@router.post("/release")
def release(req: ReleaseRequest):
    """Quita el veto. No promociona: el modelo solo entra en producción si
    además está en data/models.json y pasa el evaluador."""
    if not quarantine.release(req.model):
        raise HTTPException(status_code=404, detail="ese modelo no estaba vetado")
    return {"released": req.model}


class DeleteRequest(BaseModel):
    model: str
    confirm: str   # el operador escribe la versión (p. ej. "n20261020")


@router.post("/delete")
def delete_model(req: DeleteRequest):
    """Borra el modelo de Ollama. Irreversible para Ollama (los pesos LoRA
    siguen en training/adapters/), así que exige escribir la versión exacta.
    Sus casos y su memoria se conservan como prueba."""
    if req.model not in memory.quarantined_models():
        raise HTTPException(status_code=404, detail="ese modelo no está en cuarentena")
    if req.model in quarantine.deleted():
        raise HTTPException(status_code=400, detail="ya estaba eliminado")
    version = req.model.split(":")[-1]
    if req.confirm.strip() != version:
        raise HTTPException(status_code=400, detail=f"para confirmar escribe la versión exacta: {version}")
    try:
        detail = quarantine.decide(req.model, "eliminar")
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=f"no se pudo borrar de Ollama: {exc}") from exc
    return {"deleted": req.model, "detail": detail}


@router.get("/archive")
def archive_list():
    return {"docs": archive.list_docs()}


@router.get("/archive/{name}")
def archive_read(name: str):
    try:
        return archive.read_doc(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="documento no encontrado") from exc
