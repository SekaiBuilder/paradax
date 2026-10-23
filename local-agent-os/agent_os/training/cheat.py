from __future__ import annotations

"""Detector de trampas: ¿el alumno llegó al resultado o encontró un atajo?

Un alumno puede pasar todas las métricas sin haber resuelto la tarea: copiando
un ejemplo memorizado, devolviendo siempre lo mismo, repitiendo la entrada o
entregando un spec hueco que el Validador acepta. Eso es TRAMPA: el resultado
parece correcto pero no se llegó a él adecuadamente.

Señales (todas de categoría "trampa"):
  memoriza       la salida es casi idéntica (≥ 80 %) a un ejemplo de
                 entrenamiento, aunque la entrada sea distinta
  constante      la misma salida para entradas diferentes
  eco            la salida es sobre todo la entrada repetida (≥ 70 %)
  hueco          pasa el contrato pero sin contenido: prompt mínimo, schema
                 trivial o encargos vacíos
  desconectado   la salida no comparte ni una palabra clave con la tarea
  generico       nombres de relleno ("agente 1", "agent2"…)

Los tramposos NO se borran: van a cuarentena, quedan vetados en producción y
tú decides en la entrevista si se eliminan o se reasignan a otra tarea.
"""

import json
import re
from pathlib import Path
from typing import Any

_WORD = re.compile(r"[a-záéíóúñü0-9]+")
_STOP = set("""el la los las de del y o a en con por para que un una unos unas es se su sus al
lo como más mas este esta estos estas the of and to in for a an is on with que""".split())
_GENERIC = re.compile(r"^\s*(agente|agent|bot|asistente)[\s_-]*\d+\s*$", re.I)

MEMO_THRESHOLD = 0.80
ECHO_THRESHOLD = 0.70


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _shingles(text: str, k: int = 5) -> set[tuple[str, ...]]:
    w = _words(text)
    return {tuple(w[i:i + k]) for i in range(max(0, len(w) - k + 1))}


def _jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _text(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True) if not isinstance(obj, str) else obj


def _keywords(text: str) -> set[str]:
    return {w for w in _words(text) if len(w) > 3 and w not in _STOP}


class TrainingIndex:
    """Shingles de las salidas de entrenamiento de un agente (para 'memoriza')."""

    def __init__(self, dataset: Path) -> None:
        self.items: list[set] = []
        if dataset.exists():
            for line in dataset.read_text(encoding="utf-8").splitlines():
                try:
                    content = json.loads(line)["messages"][-1]["content"]
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                try:  # misma normalización que _text(): claves ordenadas
                    content = _text(json.loads(content))
                except (json.JSONDecodeError, TypeError):
                    pass
                sh = _shingles(content)
                if sh:
                    self.items.append(sh)

    def closest(self, text: str) -> float:
        sh = _shingles(text)
        return max((_jaccard(sh, t) for t in self.items), default=0.0)


def audit_dataset(agent_id: str, src: Path, dst: Path) -> tuple[int, dict[str, int]]:
    """Copia a `dst` solo los ejemplos que el alumno podría imitar sin quedar
    vetado: fuera los que el detector marcaría como escape (señal alta) o
    trampa. Un 1 % de ejemplos tramposos basta para que el alumno lo aprenda.
    Devuelve (conservados, {código: descartados})."""
    from .anomaly import HIGH, detect
    kept: list[str] = []
    dropped: dict[str, int] = {}
    for line in src.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            messages = json.loads(line)["messages"]
            raw = json.loads(messages[-1]["content"])
            task = next((m["content"] for m in messages if m.get("role") == "user"), "")
        except (json.JSONDecodeError, KeyError, IndexError, TypeError):
            dropped["ilegible"] = dropped.get("ilegible", 0) + 1
            continue
        codes = [s["code"] for s in detect(agent_id, raw) if s["severity"] == HIGH]
        codes += [s["code"] for s in detect_cheat(agent_id, task, raw)]
        if codes:
            for code in set(codes):
                dropped[code] = dropped.get(code, 0) + 1
            continue
        kept.append(line)
    dst.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return len(kept), dropped


def detect_cheat(
    agent_id: str,
    task: str,
    raw: Any,
    *,
    index: TrainingIndex | None = None,
    same_model_outputs: list[Any] | None = None,
) -> list[dict[str, str]]:
    """Señales de trampa de UNA salida. `task` es la entrada que recibió."""
    signals: list[dict[str, str]] = []

    def flag(code: str, detail: str) -> None:
        signals.append({"severity": "trampa", "code": code, "detail": detail[:300]})

    if not isinstance(raw, dict):
        return signals
    out = _text(raw)

    if index is not None:
        sim = index.closest(out)
        if sim >= MEMO_THRESHOLD:
            flag("memoriza", f"{sim:.0%} idéntica a un ejemplo de entrenamiento")

    if same_model_outputs:
        twins = sum(1 for o in same_model_outputs if o is not raw and _text(o) == out)
        if twins:
            flag("constante", f"misma salida que en otros {twins} casos distintos")

    out_sh, task_sh = _shingles(out, 4), _shingles(task, 4)
    if out_sh and len(out_sh & task_sh) / len(out_sh) >= ECHO_THRESHOLD:
        flag("eco", "la salida es sobre todo la entrada repetida")

    task_kw = _keywords(task)
    if task_kw and len(_keywords(out)) > 5 and not (task_kw & _keywords(out)):
        flag("desconectado", "ninguna palabra clave de la tarea aparece en la salida")

    if agent_id == "constructor":
        prompt = str(raw.get("prompt") or "")
        schema = raw.get("output_schema") or {}
        if len(prompt) < 60:
            flag("hueco", f"prompt mínimo ({len(prompt)} caracteres)")
        if isinstance(schema, dict) and len(schema) == 1 and next(iter(schema)) in ("result", "output", "data", "resultado"):
            flag("hueco", f"output_schema trivial: {schema}")
    elif agent_id == "skills_definer":
        for b in raw.get("briefs") or []:
            if isinstance(b, dict):
                need, name = str(b.get("need") or ""), str(b.get("agent_name") or "")
                if len(need) < 20 or need.strip().lower() == name.strip().lower():
                    flag("hueco", f"encargo vacío para '{name}': '{need}'")
                    break
    elif agent_id == "team_planner":
        names = [str(a.get("name") or "") for a in raw.get("agents") or [] if isinstance(a, dict)]
        generic = [n for n in names if _GENERIC.match(n)]
        if generic:
            flag("generico", f"nombres de relleno: {generic}")

    return signals
