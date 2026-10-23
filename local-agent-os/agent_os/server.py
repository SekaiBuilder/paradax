from __future__ import annotations

"""Servidor de Paradax: arranque, seguridad de red local y montaje de áreas.

Cada área vive en su propio router (agent_os/api/routes/):

  core        página, salud, modelos, actividad en vivo, runs
  projects    proyectos, Project Manager, ejecución, equipo
  hierarchy   organigrama por proyecto y grafo del Team Constructor
  agents      chat directo con agentes
  factory     Team Constructor: construir agentes, fichas, skills, fantasma
  training    alumnos, Entrenador, destilación, especialización
  lab         Laboratorio: cuarentena, archivo y entrevistas aisladas
  automation  programaciones y smart schedules
  research    Investigador: navegación online acotada
  media       pipeline del Media Manager
"""

import asyncio
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, project_runner
from .api.routes import agents, automation, core, factory, hierarchy, lab, media, projects, research, training
from .api.state import PM, _project_visible  # noqa: F401 — re-export usado por tests
from .config import ROOT, ensure_dirs
from .factory.loader import DYNAMIC


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    db.init_db()
    DYNAMIC.load_all()  # agentes construidos persistidos → vuelven al registro vivo

    async def _smart_run(project_id: str, schedule_id: str):
        """Callback del smart scheduler: lanza el run con deadline awareness."""
        p = PM.store.get(project_id)
        if not p:
            return
        from .automation.smart_scheduler import all_schedules
        sched = next((s for s in all_schedules() if s["id"] == schedule_id), None)
        deadline = sched.get("deadline_time", "") if sched else ""
        try:
            await project_runner.run_project(
                p, schedule_id=schedule_id, deadline_time=deadline
            )
        except Exception:
            pass

    from .automation.smart_scheduler import scheduler_loop_smart
    sched_task = asyncio.create_task(scheduler_loop_smart(_smart_run))
    try:
        yield
    finally:
        sched_task.cancel()


app = FastAPI(title="Paradax", version="0.2.0", lifespan=lifespan)

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}


@app.middleware("http")
async def local_only(request, call_next):
    """El servidor solo escucha en 127.0.0.1, pero eso no basta: una web
    cualquiera abierta en el navegador puede mandar peticiones a localhost
    (CSRF) o resolver su dominio a 127.0.0.1 (DNS rebinding). Se rechaza
    cualquier Host que no sea local y cualquier Origin ajeno."""
    host = urlsplit("//" + (request.headers.get("host") or "")).hostname
    if host not in _LOCAL_HOSTS:
        return JSONResponse({"detail": "host no permitido"}, status_code=403)
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).hostname not in _LOCAL_HOSTS:
        return JSONResponse({"detail": "origen no permitido"}, status_code=403)
    response = await call_next(request)
    # WKWebView (la app de escritorio) cachea los estáticos de forma agresiva
    # y serviría HTML/CSS/JS viejos tras cada cambio.
    if request.url.path == "/" or request.url.path.startswith("/static"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

for module in (core, projects, hierarchy, agents, factory, training, lab, research, automation, media):
    app.include_router(module.router)
