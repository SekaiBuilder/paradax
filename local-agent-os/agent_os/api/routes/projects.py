from __future__ import annotations

"""Proyectos: CRUD, chat con el Project Manager, ejecución, plan, equipo."""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ... import ollama, project_runner
from ...config import DEFAULT_MODEL, PM_MODEL
from ...factory.loader import DYNAMIC
from ..state import (
    PM, ChatRequest, in_language, project_chat_histories,
    spawn, _is_task_request, _launch_project_task, _project_edits_code,
)

router = APIRouter()


# ── Proyectos ──────────────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str
    goal: str = ""
    description: str = ""


@router.get("/api/projects")
def projects_list():
    return {"projects": [
        {"id": p.id, "name": p.name, "goal": p.goal, "status": p.status, "agents": p.agents}
        for p in PM.store.all()
    ]}


@router.post("/api/projects")
def projects_create(req: ProjectCreate):
    p = PM.store.create(req.name, goal=req.goal, description=req.description)
    return p.model_dump()


@router.get("/api/projects/{project_id}")
def project_detail(project_id: str):
    p = PM.store.get(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="proyecto no encontrado")
    return p.model_dump()


@router.delete("/api/projects/{project_id}")
def project_delete(project_id: str, with_agents: bool = True):
    """Borra un proyecto. Por defecto también borra sus agentes (solo viven en él)."""
    p = PM.store.get(project_id)
    removed_agents: list[str] = []
    if p and with_agents:
        for aid in list(p.agents):
            if DYNAMIC.unregister(aid):
                removed_agents.append(aid)
    return {"removed": PM.store.remove(project_id), "removed_agents": removed_agents}


@router.post("/api/projects/{project_id}/build")
async def project_build(project_id: str, model: str = PM_MODEL):
    """Lanza la construcción del equipo en segundo plano. El progreso se sigue
    por SSE (/api/events) y por GET /api/projects/{id}."""
    project = PM.store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="proyecto no encontrado")

    async def _run():
        try:
            await PM.build_team(project, model=model)
        except Exception:
            return  # project_build_finished(failed) ya informó
        # Modo automático: si el equipo quedó listo, el pipeline corre solo.
        p = PM.store.get(project_id)
        if p and p.auto_run and p.agents:
            try:
                await project_runner.run_project(p, model=model)
            except Exception:
                pass  # project_run_finished(failed) ya informó

    spawn(_run())
    return {"launched": True, "project": project_id}


@router.get("/api/projects/{project_id}/results")
def project_results(project_id: str):
    """Runs materializados del proyecto: carpetas con los archivos producidos."""
    from ...artifacts import list_results
    return {"results": list_results(project_id)}


@router.post("/api/projects/{project_id}/results/open")
def project_results_open(project_id: str, run: str = ""):
    """Abre la carpeta de resultados en Finder (app local de escritorio)."""
    import subprocess
    from ...artifacts import RESULTS_DIR, _slug
    base = RESULTS_DIR / _slug(project_id)
    target = (base / run) if run else base
    if not target.exists():
        raise HTTPException(status_code=404, detail="aún no hay resultados — ejecuta el proyecto")
    subprocess.Popen(["open", str(target)])
    return {"ok": True, "opened": str(target)}


class AutoRunReq(BaseModel):
    enabled: bool


@router.post("/api/projects/{project_id}/auto-run")
def project_auto_run(project_id: str, req: AutoRunReq):
    """Cambia el modo de ejecución del pipeline: manual (botón) o automático
    (corre solo cuando el equipo queda listo tras construirse)."""
    p = PM.store.get(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="proyecto no encontrado")
    p.auto_run = req.enabled
    p.note(f"PM: modo de ejecución → {'automático' if req.enabled else 'manual'}")
    PM.store.save(p)
    return {"ok": True, "auto_run": p.auto_run}


@router.post("/api/projects/{project_id}/chat")
async def project_chat(project_id: str, req: ChatRequest):
    project = PM.store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="proyecto no encontrado")

    if project.agents and _is_task_request(req.message):
        # El chat lanza la tarea directamente. Es seguro porque cada run tiene
        # red completa: snapshot previo + «↩ Deshacer último run» + sandbox
        # (Sentinel-Watch) + auditoría post-run con rollback automático.
        edits_code = _project_edits_code(project)
        launched = _launch_project_task(project_id, req.message, req.model)

        async def generate_action():
            text = (
                f"Entendido. Convertí tu mensaje en la tarea {launched['task']['id']} "
                "y lancé el equipo del proyecto. Puedes seguir el progreso en la "
                "actividad en vivo; al terminar quedará el run y el reporte en la "
                "bitácora del proyecto."
            )
            if edits_code:
                text += (
                    "\n\n⚠️ Esta tarea puede MODIFICAR código. Tranquilo: guardé un "
                    "snapshot previo — si el resultado no te convence, pulsa "
                    "«↩ Deshacer último run» y todo vuelve a como estaba."
                )
            yield f"data: {json.dumps({'chunk': text}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            generate_action(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    persona = in_language(PM.persona(project), req.lang)
    history = project_chat_histories.setdefault(project_id, [])
    history.append({"role": "user", "content": req.message})

    async def generate():
        full = ""
        try:
            async for chunk in ollama.stream_chat(req.model, persona, history):
                full += chunk
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
            history.append({"role": "assistant", "content": full})
            yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            if history and history[-1]["role"] == "user":
                history.pop()
            yield f"data: {json.dumps({'error': str(exc)[:500]}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Ejecutar proyecto (automatizar) ─────────────────────────────────────────────

@router.post("/api/projects/{project_id}/run")
async def project_run(project_id: str, model: str = DEFAULT_MODEL):
    """Ejecuta el PIPELINE del proyecto en segundo plano (correrlo, no solo
    construir el equipo). El progreso se sigue por SSE (/api/events)."""
    project = PM.store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="proyecto no encontrado")

    async def _run():
        try:
            await project_runner.run_project(project, model=model)
        except Exception:
            pass  # project_run_finished(failed) ya informó

    spawn(_run())
    return {"launched": True, "project": project_id}


@router.get("/api/projects/{project_id}/plan")
def project_plan(project_id: str):
    """Previsualiza el pipeline armado desde los contratos (reads/writes): orden,
    qué lee/escribe cada agente, qué le falta, y los edges de flujo de datos."""
    project = PM.store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="proyecto no encontrado")
    seed = set(project_runner.task_inputs(project, project.goal or project.name).keys())
    return project_runner.compute_plan(project, seed)


@router.post("/api/projects/{project_id}/undo")
def project_undo(project_id: str):
    """Deshace el último run de agentes del proyecto (revierte el árbol git)."""
    project = PM.store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="proyecto no encontrado")
    before = ""
    for task in reversed(project.tasks):
        undo = task.result.get("undo") if isinstance(task.result, dict) else None
        if undo and undo.get("before_sha"):
            before = undo["before_sha"]
            break
    if not before:
        raise HTTPException(status_code=400, detail="no hay un run reciente que deshacer")
    from ...factory import safety
    res = safety.undo_to(before)
    if res.get("ok"):
        DYNAMIC.load_all()  # por si se revirtieron specs de agentes
    return res


@router.get("/api/projects/{project_id}/tasks")
def project_tasks(project_id: str):
    project = PM.store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="proyecto no encontrado")
    return {"tasks": [t.model_dump() for t in project.tasks]}


class ProjectInputs(BaseModel):
    inputs: dict = {}


@router.post("/api/projects/{project_id}/inputs")
def project_set_inputs(project_id: str, req: ProjectInputs):
    """Define el contexto SEMILLA del proyecto (lo que ningún agente produce:
    p. ej. url + idioma para social media, o credenciales/fuente para IG)."""
    project = PM.store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="proyecto no encontrado")
    project.inputs = req.inputs
    PM.store.save(project)
    return project.model_dump()


# ── Agentes de un proyecto (añadir / quitar) ────────────────────────────────────

class AgentRef(BaseModel):
    agent_id: str


@router.post("/api/projects/{project_id}/agents")
def project_add_agent(project_id: str, ref: AgentRef):
    project = PM.store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="proyecto no encontrado")
    agent = DYNAMIC.get(ref.agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agente no encontrado")
    if ref.agent_id not in project.agents:
        project.agents.append(ref.agent_id)
        project.note(f"agente añadido al equipo: {ref.agent_id}")
        PM.store.save(project)
    # Marca el proyecto en el spec y re-persiste (así aparece en su grafo).
    if getattr(agent, "spec", None) is not None:
        agent.spec.project = project_id
        DYNAMIC.register(agent.spec)
    return project.model_dump()


@router.delete("/api/projects/{project_id}/agents/{agent_id}")
def project_remove_agent(project_id: str, agent_id: str):
    project = PM.store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="proyecto no encontrado")
    if agent_id in project.agents:
        project.agents.remove(agent_id)
        project.note(f"agente quitado del equipo: {agent_id}")
        PM.store.save(project)
    agent = DYNAMIC.get(agent_id)
    if agent is not None and getattr(agent, "spec", None) is not None:
        agent.spec.project = ""
        DYNAMIC.register(agent.spec)
    return project.model_dump()
