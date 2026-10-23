from __future__ import annotations

"""Smart Scheduler: extiende el scheduler básico con deadline awareness.

Diferencia clave con scheduler.py:
- scheduler.py  → dispara exactamente a la hora configurada
- smart_scheduler → dispara a `deadline - estimado` para que la tarea
  TERMINE antes del deadline (no que empiece a esa hora)

Schema de schedule inteligente:
{
  "id": "...",
  "project_id": "...",
  "deadline_time": "03:00",     # hora objetivo de FINALIZACIÓN
  "days_of_month": [1..31],
  "task_kind": "media",         # para DurationTracker
  "default_duration_minutes": 90,  # estimado inicial si no hay historial
  "label": "...",
  "enabled": True,
  "last_fired": "",
  "last_duration_seconds": 0,
}

Funciones puras (sin side effects) para fácil testing:
  compute_start_time(deadline, estimated_seconds) → "HH:MM"
  should_fire(schedule, now, tracker) → bool

El loop asyncio está en scheduler_loop_smart() — se usa en server.py.
"""

import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable

from ..config import DATA_DIR
from ..core.events import BUS
from .duration_tracker import DurationTracker

SMART_SCHEDULES_FILE = DATA_DIR / "smart_schedules.json"


# ── Persistencia ──────────────────────────────────────────────────────────────

def _load() -> list[dict[str, Any]]:
    if SMART_SCHEDULES_FILE.exists():
        try:
            return json.loads(SMART_SCHEDULES_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _save(items: list[dict[str, Any]]) -> None:
    SMART_SCHEDULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    SMART_SCHEDULES_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def all_schedules() -> list[dict[str, Any]]:
    return _load()


def create_schedule(
    project_id: str,
    deadline_time: str,
    days_of_month: list[int],
    task_kind: str = "system",
    default_duration_minutes: int = 60,
    label: str = "",
    enabled: bool = True,
) -> dict[str, Any]:
    days = sorted({int(d) for d in days_of_month if 1 <= int(d) <= 31})
    s = {
        "id": uuid.uuid4().hex[:8],
        "project_id": project_id,
        "deadline_time": deadline_time.strip(),
        "days_of_month": days,
        "task_kind": task_kind,
        "default_duration_minutes": default_duration_minutes,
        "label": label,
        "enabled": enabled,
        "created_at": time.time(),
        "last_fired": "",
        "last_duration_seconds": 0.0,
    }
    items = _load()
    items.append(s)
    _save(items)
    return s


def delete_schedule(sid: str) -> bool:
    items = _load()
    kept = [s for s in items if s["id"] != sid]
    _save(kept)
    return len(kept) < len(items)


def toggle_schedule(sid: str, enabled: bool) -> bool:
    items = _load()
    found = False
    for s in items:
        if s["id"] == sid:
            s["enabled"] = enabled
            found = True
    if found:
        _save(items)
    return found


# ── Lógica de tiempo (puras, sin side effects) ────────────────────────────────

def compute_start_time(deadline: str, estimated_seconds: float) -> str:
    """Dado un deadline 'HH:MM' y una duración estimada en segundos,
    devuelve la hora a la que hay que LANZAR la tarea para terminar a tiempo.

    Ejemplo: deadline='03:00', estimated_seconds=5400 (90min) → '01:30'
    """
    h, m = map(int, deadline.split(":"))
    deadline_dt = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
    start_dt = deadline_dt - timedelta(seconds=estimated_seconds)
    return start_dt.strftime("%H:%M")


def should_fire(schedule: dict[str, Any], now: datetime, tracker: DurationTracker) -> bool:
    """True si el schedule debe dispararse en este momento (comprueba cada minuto)."""
    if not schedule.get("enabled"):
        return False
    if now.day not in schedule.get("days_of_month", []):
        return False
    # Anti-duplicado: un disparo por minuto
    if schedule.get("last_fired") == now.strftime("%Y-%m-%d %H:%M"):
        return False

    estimated = tracker.estimated_seconds(
        schedule["project_id"],
        schedule.get("task_kind", "system"),
        schedule.get("default_duration_minutes", 60),
    )
    start_time = compute_start_time(schedule["deadline_time"], estimated)
    return now.strftime("%H:%M") == start_time


def schedule_with_estimate(schedule: dict[str, Any], tracker: DurationTracker) -> dict[str, Any]:
    """Añade metadatos de estimación a un schedule para la UI."""
    estimated = tracker.estimated_seconds(
        schedule["project_id"],
        schedule.get("task_kind", "system"),
        schedule.get("default_duration_minutes", 60),
    )
    start_time = compute_start_time(schedule["deadline_time"], estimated)
    return {
        **schedule,
        "_estimated_minutes": round(estimated / 60, 1),
        "_start_time": start_time,
        "_summary": tracker.summary(
            schedule["project_id"], schedule.get("task_kind", "system")
        ),
    }


# ── Loop asyncio ──────────────────────────────────────────────────────────────

async def scheduler_loop_smart(
    run_callback: Callable[[str, str], Awaitable[Any]],
    tracker: DurationTracker | None = None,
) -> None:
    """Loop que comprueba cada 30s y dispara cuando now() == start_time.

    run_callback(project_id, schedule_id) → debe lanzar el run sin bloquear.
    """
    if tracker is None:
        tracker = DurationTracker()
    while True:
        try:
            now = datetime.now()
            items = _load()
            changed = False
            for s in items:
                if should_fire(s, now, tracker):
                    s["last_fired"] = now.strftime("%Y-%m-%d %H:%M")
                    changed = True
                    BUS.publish("smart_schedule_fired", {
                        "schedule": s["id"],
                        "project": s["project_id"],
                        "task_kind": s.get("task_kind"),
                        "deadline": s["deadline_time"],
                        "at": s["last_fired"],
                    })
                    asyncio.create_task(run_callback(s["project_id"], s["id"]))
            if changed:
                _save(items)
        except Exception:
            pass
        await asyncio.sleep(30)


def update_last_duration(schedule_id: str, duration_seconds: float) -> None:
    """Llamado por project_runner al terminar un run para refinar el estimado."""
    items = _load()
    for s in items:
        if s["id"] == schedule_id:
            s["last_duration_seconds"] = round(duration_seconds, 1)
    _save(items)
