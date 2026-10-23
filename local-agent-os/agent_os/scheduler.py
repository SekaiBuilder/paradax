from __future__ import annotations

"""Programador de proyectos: corre el pipeline de un proyecto en los DÍAS DEL
MES y HORAS que elijas. Loop in-process (vive mientras Paradax esté abierto).

Schedule: {id, project_id, days_of_month:[1..31], times:["HH:MM"], enabled, label, last_fired}
Guardado en data/schedules.json.
"""

import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable

from .config import DATA_DIR
from .core.events import BUS

SCHEDULES_FILE = DATA_DIR / "schedules.json"


def _load() -> list[dict[str, Any]]:
    if SCHEDULES_FILE.exists():
        try:
            return json.loads(SCHEDULES_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _save(items: list[dict[str, Any]]) -> None:
    SCHEDULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULES_FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def all_schedules() -> list[dict[str, Any]]:
    return _load()


def create_schedule(project_id: str, days_of_month: list[int], times: list[str],
                    label: str = "", enabled: bool = True) -> dict[str, Any]:
    days = sorted({int(d) for d in days_of_month if 1 <= int(d) <= 31})
    clean_times = sorted({t.strip() for t in times if _valid_time(t)})
    s = {
        "id": uuid.uuid4().hex[:8],
        "project_id": project_id,
        "days_of_month": days,
        "times": clean_times,
        "label": label,
        "enabled": enabled,
        "created_at": time.time(),
        "last_fired": "",
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
    _save(items)
    return found


def _valid_time(t: str) -> bool:
    try:
        h, m = t.strip().split(":")
        return 0 <= int(h) <= 23 and 0 <= int(m) <= 59
    except (ValueError, AttributeError):
        return False


def _matches(s: dict[str, Any], now: datetime) -> bool:
    if not s.get("enabled"):
        return False
    if now.day not in s.get("days_of_month", []):
        return False
    if now.strftime("%H:%M") not in s.get("times", []):
        return False
    return s.get("last_fired") != now.strftime("%Y-%m-%d %H:%M")  # 1 disparo por minuto


async def scheduler_loop(run_callback: Callable[[str], Awaitable[Any]]) -> None:
    """Cada 30s comprueba los schedules y dispara run_callback(project_id) cuando
    coincide día+hora. run_callback debe lanzar el run (no bloquear)."""
    while True:
        try:
            now = datetime.now()
            items = _load()
            changed = False
            for s in items:
                if _matches(s, now):
                    s["last_fired"] = now.strftime("%Y-%m-%d %H:%M")
                    changed = True
                    BUS.publish("schedule_fired",
                                {"schedule": s["id"], "project": s["project_id"], "at": s["last_fired"]})
                    asyncio.create_task(run_callback(s["project_id"]))
            if changed:
                _save(items)
        except Exception:
            pass  # un fallo del loop nunca debe tumbar el servidor
        await asyncio.sleep(30)
