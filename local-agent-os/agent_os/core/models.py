from __future__ import annotations

"""Resolución del modelo por agente.

`data/models.json` lo escribe el evaluador al promocionar un alumno apto
(agente → modelo Ollama). En producción, cada agente consulta aquí qué modelo
usar: el alumno especializado si está promocionado, o el maestro (el modelo
del request) si no hay ninguno.
"""

import json
import os

from ..config import DATA_DIR

MODELS_FILE = DATA_DIR / "models.json"


def resolve_model(agent_id: str, fallback: str) -> tuple[str, bool]:
    """Devuelve (modelo, es_alumno). es_alumno=True si hay un modelo
    promocionado para este agente en models.json."""
    if fallback.startswith("9r/") or os.getenv("PARADAX_TEACHER_MODE") == "1":
        # Maestro de 9router pedido explícitamente (entrenamiento nocturno):
        # gana al alumno, o el alumno acabaría aprendiendo de sí mismo.
        return fallback, False
    try:
        if MODELS_FILE.exists():
            mapping = json.loads(MODELS_FILE.read_text(encoding="utf-8"))
            model = mapping.get(agent_id)
            if model and _is_vetoed(model):
                return fallback, False  # alumno en cuarentena: manda el maestro
            if model:
                return str(model), True
    except (json.JSONDecodeError, OSError):
        pass  # models.json corrupto no debe romper producción: cae al maestro
    return fallback, False


def _is_vetoed(model: str) -> bool:
    try:
        from ..training.quarantine import is_vetoed
        return is_vetoed(model)
    except Exception:
        return False
