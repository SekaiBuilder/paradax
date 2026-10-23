from __future__ import annotations

"""DurationTracker: aprende del historial real de duraciones de runs.

Guarda un caché compacto en data/durations.json. Cada entrada es:
  project_id → task_kind → [lista de duraciones en segundos, más recientes primero]

Al calcular el estimado usa los últimos N runs completados (+20% de buffer de
seguridad) para que el Guardián del tiempo tenga margen de error.
"""

import json
import time
from pathlib import Path
from typing import Any

from ..config import DATA_DIR

DURATIONS_FILE = DATA_DIR / "durations.json"
MAX_HISTORY = 10   # cuántos runs guardar por (project, task_kind)
BUFFER_FACTOR = 1.2   # +20% de margen de seguridad sobre el promedio


def _load() -> dict[str, Any]:
    if DURATIONS_FILE.exists():
        try:
            return json.loads(DURATIONS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save(data: dict[str, Any]) -> None:
    DURATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    DURATIONS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class DurationTracker:
    def record(self, project_id: str, task_kind: str, duration_seconds: float) -> None:
        """Registra la duración de un run completado."""
        data = _load()
        bucket = data.setdefault(project_id, {}).setdefault(task_kind, [])
        bucket.insert(0, round(duration_seconds, 1))
        data[project_id][task_kind] = bucket[:MAX_HISTORY]
        _save(data)

    def history(self, project_id: str, task_kind: str) -> list[float]:
        """Devuelve el historial de duraciones (más reciente primero)."""
        data = _load()
        return data.get(project_id, {}).get(task_kind, [])

    def estimated_seconds(
        self,
        project_id: str,
        task_kind: str,
        default_minutes: int = 60,
    ) -> float:
        """Estimado con buffer. Si no hay historial usa default_minutes."""
        hist = self.history(project_id, task_kind)
        if not hist:
            return default_minutes * 60 * BUFFER_FACTOR
        avg = sum(hist) / len(hist)
        return avg * BUFFER_FACTOR

    def start_offset_seconds(
        self,
        project_id: str,
        task_kind: str,
        default_minutes: int = 60,
    ) -> float:
        """Cuántos segundos antes del deadline hay que lanzar la tarea."""
        return self.estimated_seconds(project_id, task_kind, default_minutes)

    def summary(self, project_id: str, task_kind: str) -> dict[str, Any]:
        hist = self.history(project_id, task_kind)
        if not hist:
            return {"runs": 0, "avg_minutes": None, "estimated_minutes": None}
        avg_s = sum(hist) / len(hist)
        est_s = avg_s * BUFFER_FACTOR
        return {
            "runs": len(hist),
            "avg_minutes": round(avg_s / 60, 1),
            "estimated_minutes": round(est_s / 60, 1),
            "buffer_factor": BUFFER_FACTOR,
        }
