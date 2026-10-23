from __future__ import annotations

"""Media Manager: pipeline GIF/reel."""


from fastapi import APIRouter, HTTPException

from ...orchestrator import (
    MediaRunRequest, UnsupportedMediaRequest, is_media_request, run_media_manager,
)
from ...tools.media import active_project
from ..state import running_tasks as _running_tasks, spawn

router = APIRouter()


# ── Media Manager ─────────────────────────────────────────────────────────────

@router.get("/api/media-manager/project")
def media_project():
    return active_project()


@router.post("/api/agents/media-manager/run")
async def media_run(req: MediaRunRequest):
    try:
        return await run_media_manager(req)
    except UnsupportedMediaRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# Tareas en vuelo: guardamos la referencia para que el GC no las cancele.


@router.post("/api/agents/media-manager/launch")
async def media_launch(req: MediaRunRequest):
    """Dispara el run en segundo plano y devuelve al instante. La actividad se
    sigue por SSE (/api/events). No bloquea la petición ni la UI."""
    if not is_media_request(req.request):
        raise HTTPException(
            status_code=400,
            detail=(
                "El Media Manager solo acepta pedidos de GIF/reel/demo. "
                "Para reprogramar Paradax usa Proyectos o Codex."
            ),
        )

    async def _run():
        try:
            await run_media_manager(req)
        except Exception:
            pass  # el evento run_finished(failed) ya informó del error

    spawn(_run())
    return {"launched": True, "active_tasks": len(_running_tasks)}
