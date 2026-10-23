from __future__ import annotations

"""Proposer adaptativo (Multi-Agent Evolve, forma tratable).

El generador base propone tareas AL AZAR. Este Proposer aprende de la señal de
calidad (`source` de cada agente) qué CARACTERÍSTICAS de tarea exponen las
debilidades del Solver, y sesga la generación hacia ellas. Así los ~100 ejemplos
que alimentan la destilación se concentran donde el agente falla — currículo
automático, no ruido uniforme.

Diseño factored-bandit (eficiente con pocos datos): en vez de tratar cada combo
tema×tono×plataforma como una casilla (360, demasiado escasas), aprende una tasa
de debilidad POR VALOR de cada dimensión y puntúa un combo por la media de sus
componentes + un bono de exploración para lo poco visto. Memoria persistida en
data/proposer_memory.json.

Quality → weakness:
    source "model"          → 0.0  (acertó a la primera: tarea fácil)
    source "model_retry_N"  → 0.5..0.9  (le costó)
    source "fallback:…"     → 1.0  (falló: máxima debilidad)
"""

import json
import math
import random
from typing import Any

from ..config import DATA_DIR

MEMORY_FILE = DATA_DIR / "proposer_memory.json"

# El espacio de tareas del proyecto social (dimensiones independientes).
DIMS: dict[str, list[str]] = {
    "tema": [
        "el café de especialidad", "caminar 30 minutos al día", "ahorrar en la compra",
        "fotografía móvil", "cenas rápidas de semana", "dormir mejor",
        "plantas de interior", "aprender japonés", "estiramientos de oficina",
        "podcasts de historia", "escritorio minimalista", "viajar barato",
        "ayuno intermitente", "libros cortos", "pan casero", "meditación",
        "bicicleta urbana", "controlar gastos", "descanso sin pantallas",
        "senderismo urbano", "batidos verdes", "paisajes al amanecer",
        "cuidar la voz", "juegos de mesa", "escribir un diario",
        "maridaje queso y vino", "dolor de espalda", "compost en casa",
        "skincare minimalista", "método pomodoro",
    ],
    "tono": ["cercano y motivador", "informativo y directo", "divertido con humor", "inspirador"],
    "plataforma": ["Instagram", "LinkedIn", "X (Twitter)"],
}


def _quality_from_source(source: str) -> float:
    if source.startswith("fallback"):
        return 0.0
    if source.startswith("model_retry"):
        try:
            n = int(source.rsplit("_", 1)[-1])
        except ValueError:
            n = 1
        return max(0.1, 1.0 - 0.4 * n)  # cada reintento resta
    return 1.0  # "model": limpio


def _load() -> dict[str, Any]:
    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(mem: dict[str, Any]) -> None:
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")


def _stats(mem: dict, dim: str, value: str) -> tuple[float, int]:
    """(tasa_de_debilidad, nº_de_muestras) de un valor de dimensión."""
    key = f"{dim}::{value}"
    rec = mem.get(key)
    if not rec or rec["n"] == 0:
        return 0.5, 0  # prior neutro para lo no visto
    return 1.0 - rec["quality_sum"] / rec["n"], rec["n"]


def record(request_dims: dict[str, str], quality: float) -> None:
    """Registra la calidad observada de un run con sus dimensiones."""
    mem = _load()
    for dim, value in request_dims.items():
        key = f"{dim}::{value}"
        rec = mem.setdefault(key, {"n": 0, "quality_sum": 0.0})
        rec["n"] += 1
        rec["quality_sum"] += quality
    _save(mem)


def score_combo(mem: dict, combo: dict[str, str]) -> float:
    """Puntúa un combo: media de debilidad de sus componentes + exploración."""
    weak_total = 0.0
    explore = 0.0
    total_n = 0
    for dim, value in combo.items():
        weakness, n = _stats(mem, dim, value)
        weak_total += weakness
        total_n += n
        explore += 1.0 / math.sqrt(n + 1)  # UCB-ish: lo poco visto sube
    k = len(combo)
    return weak_total / k + 0.25 * (explore / k)


def propose(n: int, *, seed: int | None = None) -> list[dict[str, str]]:
    """Devuelve n combos de tarea sesgados hacia las debilidades aprendidas.

    Muestreo por peso (no top-n duro): mantiene variedad pero concentra donde el
    agente flaquea. Sin memoria, es prácticamente uniforme (todo explora)."""
    mem = _load()
    rng = random.Random(seed)
    all_combos = [
        {"tema": t, "tono": to, "plataforma": p}
        for t in DIMS["tema"] for to in DIMS["tono"] for p in DIMS["plataforma"]
    ]
    scored = [(c, score_combo(mem, c)) for c in all_combos]
    # peso = score^6 para concentrar con fuerza en las debilidades, sin excluir
    # del todo el resto (siempre queda algo de exploración por el bono UCB).
    weights = [max(0.001, s) ** 6 for _, s in scored]
    chosen: list[dict[str, str]] = []
    pool = list(zip(all_combos, weights))
    for _ in range(min(n, len(pool))):
        total = sum(w for _, w in pool)
        r = rng.uniform(0, total)
        acc = 0.0
        for i, (c, w) in enumerate(pool):
            acc += w
            if acc >= r:
                chosen.append(c)
                pool.pop(i)  # sin reemplazo dentro del lote
                break
    return chosen


def to_request(combo: dict[str, str]) -> str:
    return (f"redacta un post sobre {combo['tema']} con tono {combo['tono']} "
            f"para {combo['plataforma']}")


def report(top: int = 8) -> list[dict[str, Any]]:
    """Las características más débiles aprendidas — para ver qué exige el currículo."""
    mem = _load()
    rows = []
    for key, rec in mem.items():
        if rec["n"] == 0:
            continue
        dim, value = key.split("::", 1)
        rows.append({
            "dim": dim, "value": value, "n": rec["n"],
            "debilidad": round(1.0 - rec["quality_sum"] / rec["n"], 2),
        })
    rows.sort(key=lambda r: r["debilidad"], reverse=True)
    return rows[:top]


def quality_of_run(run: dict[str, Any]) -> float:
    """Calidad global de un run = media de la calidad de sus agentes."""
    sources = [
        e["payload"].get("source", "model")
        for e in run.get("events", [])
        if e["kind"] == "agent_completed"
    ]
    if not sources:
        return 1.0
    return sum(_quality_from_source(s) for s in sources) / len(sources)
