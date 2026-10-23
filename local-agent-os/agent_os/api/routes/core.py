from __future__ import annotations

"""Núcleo: página, salud, modelos, actividad en vivo (SSE) y runs."""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from ... import db
from ...config import DEFAULT_MODEL, MEDIA_MANAGER_ROOT, ROOT
from ...core.events import BUS
from ...ollama import list_models
from ..state import running_tasks as _running_tasks

router = APIRouter()


@router.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@router.get("/api/health")
def health():
    return {
        "ok": True,
        "default_model": DEFAULT_MODEL,
        "media_manager_root": str(MEDIA_MANAGER_ROOT),
    }


@router.get("/api/models")
async def models():
    try:
        return {"models": await list_models()}
    except Exception as exc:
        return {"models": [], "error": f"Ollama no disponible: {exc}"}


# ── Actividad en vivo (SSE) ─────────────────────────────────────────────────────

@router.get("/api/activity")
def activity(limit: int = 50):
    """Foto reciente de eventos — para poblar el panel al abrir."""
    return {"events": BUS.snapshot(limit), "active_tasks": len(_running_tasks)}


@router.get("/api/events")
async def events():
    """Stream SSE de la actividad en vivo. Una sola conexión por cliente."""
    async def gen():
        # ping inicial para abrir el stream de inmediato
        yield ": connected\n\n"
        async for event in BUS.subscribe(replay=True):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ── Runs ──────────────────────────────────────────────────────────────────────

@router.get("/api/runs")
def runs(limit: int = 50):
    return {"runs": db.list_runs(limit)}


@router.get("/api/runs/{run_id}")
def run_detail(run_id: str):
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.get("/api/runs/{run_id}/sandbox")
def run_sandbox_detail(run_id: str):
    """Resumen del sandbox para un run: audit report + tool calls aprobadas/bloqueadas."""
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    events = run.get("events", [])
    audit_events = [e for e in events if e["kind"] == "audit_report"]
    sandbox_tool_events = [e for e in events if e["kind"] == "sandbox_tool"]
    sandbox_started = next((e for e in events if e["kind"] == "sandbox_started"), None)
    approved = [e for e in sandbox_tool_events if e["payload"].get("ok")]
    blocked = [e for e in sandbox_tool_events if not e["payload"].get("ok")]
    return {
        "run_id": run_id,
        "sandbox_active": sandbox_started is not None,
        "task_kind": (sandbox_started or {}).get("payload", {}).get("task_kind"),
        "broker_tools": (sandbox_started or {}).get("payload", {}).get("broker_tools", []),
        "tool_calls_total": len(sandbox_tool_events),
        "approved": len(approved),
        "blocked": len(blocked),
        "blocked_detail": [
            {
                "tool": e["payload"].get("tool"),
                "agent": e["payload"].get("agent_id"),
                "blocked_by": e["payload"].get("blocked_by"),
            }
            for e in blocked
        ],
        "audit": audit_events[-1]["payload"] if audit_events else None,
    }
