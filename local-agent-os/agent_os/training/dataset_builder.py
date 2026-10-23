from __future__ import annotations

"""Dataset Builder: convierte runs verificados en ejemplos de entrenamiento.

Regla de oro: solo entra al dataset lo que el Verifier aprobó SIN reparación.
Si un run necesitó reparar, el plan original era malo — no se aprende de él.

Salida: JSONL en formato chat de mlx-lm
    {"messages": [{"role":"system",...},{"role":"user",...},{"role":"assistant",...}]}

El system del alumno es el prompt compacto (student_planner.md) y el assistant
es el plan en formato wire — el alumno aprende a hablar el protocolo nativo.
"""

import json
import random
import sqlite3
from pathlib import Path
from typing import Any, Iterator

from ..agents.action_planner import _inventory_text, _topic_slug  # mismo texto que en producción
from ..config import DATA_DIR, ROOT
from ..core.wire import WireError, encode_plan

STUDENT_PROMPT = (
    Path(__file__).parents[1] / "agents" / "prompts" / "student_planner.md"
).read_text(encoding="utf-8")

DATASET_DIR = ROOT / "training" / "dataset"
DB_PATH = DATA_DIR / "agent_os.sqlite3"

# Fuentes de plan admitidas: del modelo (con o sin prefijo/reintento) y
# fallback determinista (comportamiento correcto verificado). Nunca "repair".
GOOD_SOURCES = ("model", "model+prefix", "model_retry", "fallback")


def harvest(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Extrae (request, inventario, plan) de cada run apto."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        runs = conn.execute("SELECT id, request, status FROM runs WHERE status='completed'").fetchall()
        examples = []
        for run in runs:
            events = conn.execute(
                "SELECT kind, payload_json FROM run_events WHERE run_id=? ORDER BY id ASC",
                (run["id"],),
            ).fetchall()
            example = _example_from_events(run["id"], run["request"], events)
            if example:
                examples.append(example)
        return examples
    finally:
        conn.close()


def _example_from_events(run_id: str, request: str, events: list[sqlite3.Row]) -> dict | None:
    inventory = plan = None
    verdicts = []
    repaired = False
    for ev in events:
        payload = json.loads(ev["payload_json"])
        if ev["kind"] == "gif_repair_started":
            repaired = True
        if ev["kind"] != "agent_completed":
            continue
        agent = payload.get("agent")
        output = payload.get("output", {})
        if agent == "page_inspector":
            inventory = output
        elif agent == "action_planner":
            plan = output
        elif agent == "verifier":
            verdicts.append(output)

    if repaired or not (inventory and plan and verdicts):
        return None
    if not verdicts[0].get("ok"):
        return None
    source = str(plan.get("plan_source", ""))
    if not source.startswith(GOOD_SOURCES):
        return None
    try:
        compact = encode_plan(plan)
    except (WireError, KeyError):
        return None
    return {
        "run_id": run_id,
        "request": request,
        "inventory": inventory,
        "compact_plan": compact,
        "plan_source": source,
    }


def to_chat(example: dict[str, Any]) -> dict[str, Any]:
    """Ejemplo → formato chat de mlx-lm. El user replica el prompt de producción."""
    user = (
        f"Pedido: {example['request']}\n"
        f"Inventario real:\n{_inventory_text(example['inventory'])}"
    )
    # Nombres de archivo limpios derivados del pedido: el modelo del maestro a
    # veces produce nombres que _safe_name mangla (kanji-53-53-53…). Enseñar
    # esos nombres degenerados sería ruido — el alumno debe aprender el patrón
    # limpio. Las acciones (la coreografía) se conservan tal cual.
    target = dict(example["compact_plan"])
    slug = _topic_slug(example["request"])
    target["f"] = f"acciones-{slug}.json"
    target["g"] = f"{slug}.gif"
    return {
        "messages": [
            {"role": "system", "content": STUDENT_PROMPT},
            {"role": "user", "content": user},
            {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)},
        ]
    }


def build(db_path: Path = DB_PATH, out_dir: Path = DATASET_DIR, valid_ratio: float = 0.1) -> dict[str, int]:
    examples = harvest(db_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Dedupe por (request, plan) — el generador repite plantillas a propósito,
    # pero ejemplos idénticos no aportan y sesgan la pérdida.
    seen: set[str] = set()
    unique = []
    for ex in examples:
        key = json.dumps([ex["request"], ex["compact_plan"]], ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            unique.append(ex)

    rng = random.Random(42)  # split reproducible entre ejecuciones
    rng.shuffle(unique)
    n_valid = max(1, int(len(unique) * valid_ratio)) if len(unique) >= 5 else 0
    valid, train = unique[:n_valid], unique[n_valid:]

    _write_jsonl(out_dir / "train.jsonl", [to_chat(e) for e in train])
    _write_jsonl(out_dir / "valid.jsonl", [to_chat(e) for e in valid])
    # Casos estructurados del split de validación: el evaluador de promoción
    # los usa para puntuar candidatos sin re-parsear prompts.
    _write_jsonl(out_dir / "valid_cases.jsonl", valid)
    _write_jsonl(out_dir / "meta.jsonl", [
        {"run_id": e["run_id"], "plan_source": e["plan_source"], "request": e["request"]}
        for e in unique
    ])
    return {"total": len(examples), "unique": len(unique), "train": len(train), "valid": len(valid)}


def _write_jsonl(path: Path, rows: Iterator[dict] | list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    stats = build()
    print(json.dumps(stats, indent=2))
