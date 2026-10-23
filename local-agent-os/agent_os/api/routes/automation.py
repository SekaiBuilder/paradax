from __future__ import annotations

"""Automatización: programaciones clásicas y smart schedules con deadline."""


from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ... import project_runner, scheduler
from ..state import PM

router = APIRouter()


# ── Programación (scheduler: días del mes + horarios) ────────────────────────────

class ScheduleCreate(BaseModel):
    project_id: str
    days_of_month: list[int]
    times: list[str]
    label: str = ""


class ToggleReq(BaseModel):
    enabled: bool


@router.get("/api/schedules")
def schedules_list():
    return {"schedules": scheduler.all_schedules()}


@router.post("/api/schedules")
def schedules_create(req: ScheduleCreate):
    if not PM.store.get(req.project_id):
        raise HTTPException(status_code=404, detail="proyecto no encontrado")
    if not req.days_of_month or not req.times:
        raise HTTPException(status_code=400, detail="elige al menos un día y una hora")
    return scheduler.create_schedule(req.project_id, req.days_of_month, req.times, req.label)


@router.delete("/api/schedules/{sid}")
def schedules_delete(sid: str):
    return {"removed": scheduler.delete_schedule(sid)}


@router.post("/api/schedules/{sid}/toggle")
def schedules_toggle(sid: str, req: ToggleReq):
    return {"ok": scheduler.toggle_schedule(sid, req.enabled)}


# ── Team Automatización: smart schedules con deadline awareness ───────────────

class SmartScheduleCreate(BaseModel):
    project_id: str
    deadline_time: str               # "HH:MM" — hora objetivo de FINALIZACIÓN
    days_of_month: list[int]
    task_kind: str = "system"
    default_duration_minutes: int = 60
    label: str = ""
    enabled: bool = True


@router.get("/api/automation/schedules")
def automation_schedules_list():
    """Lista los smart schedules con su estimado actual de inicio."""
    from ...automation.duration_tracker import DurationTracker
    from ...automation.smart_scheduler import all_schedules, schedule_with_estimate
    tracker = DurationTracker()
    return {
        "schedules": [schedule_with_estimate(s, tracker) for s in all_schedules()]
    }


@router.post("/api/automation/schedules")
def automation_schedules_create(req: SmartScheduleCreate):
    project = PM.store.get(req.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="proyecto no encontrado")
    from ...automation.smart_scheduler import create_schedule

    # El task_kind lo decide el proyecto, no el cliente: así el bucket de
    # duraciones que usa la estimación es el MISMO que registra run_project.
    task_kind = project_runner._detect_task_kind(project)
    s = create_schedule(
        project_id=req.project_id,
        deadline_time=req.deadline_time,
        days_of_month=req.days_of_month,
        task_kind=task_kind,
        default_duration_minutes=req.default_duration_minutes,
        label=req.label,
        enabled=req.enabled,
    )
    # Enriquecer con estimado para la respuesta
    from ...automation.duration_tracker import DurationTracker
    from ...automation.smart_scheduler import schedule_with_estimate
    return schedule_with_estimate(s, DurationTracker())


@router.delete("/api/automation/schedules/{sid}")
def automation_schedules_delete(sid: str):
    from ...automation.smart_scheduler import delete_schedule
    return {"removed": delete_schedule(sid)}


@router.post("/api/automation/schedules/{sid}/toggle")
def automation_schedules_toggle(sid: str, req: ToggleReq):
    from ...automation.smart_scheduler import toggle_schedule
    return {"ok": toggle_schedule(sid, req.enabled)}


@router.get("/api/automation/stats/{project_id}")
def automation_stats(project_id: str, task_kind: str = "system"):
    """Historial de duraciones para un proyecto — informa al Guardián del tiempo."""
    from ...automation.duration_tracker import DurationTracker
    tracker = DurationTracker()
    return {
        "project_id": project_id,
        "task_kind": task_kind,
        "history_seconds": tracker.history(project_id, task_kind),
        **tracker.summary(project_id, task_kind),
    }
