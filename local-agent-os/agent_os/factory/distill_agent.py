from __future__ import annotations

"""Destilador universal por agente: convierte a CUALQUIER agente construido de
'prompt + modelo genérico' en un ESPECIALISTA con modelo propio fine-tuneado.

El circuito completo (maestro → alumno), agnóstico al dominio:

  1. cosecha      — recorre los runs verificados en SQLite y saca, para el
                    agente, los pares (input real, output aprobado). Solo runs
                    'completed' cuyo agente completó sin fallar: el maestro ya
                    demostró la respuesta buena.
  2. build_dataset— escribe un JSONL en formato chat de mlx-lm reproduciendo el
                    MISMO system/user prompt que ve el agente en producción
                    (build_user_prompt), para que el alumno no vea entrada fuera
                    de distribución.
  3. train        — delega en training/train_mlx.sh <agente> <version>, que hace
                    LoRA sobre Qwen2.5-3B y publica agent-os/<agente>:<version>
                    en Ollama.
  4. promote      — registra el alumno en models.json; resolve_model() lo usa
                    automáticamente en el siguiente run (is_student=True).

Así el agente deja de "pensar con un prompt genérico" y pasa a ser un modelo
pequeño que INTERIORIZÓ su tarea — más rápido, más barato, especializado.
"""

import asyncio
import json
import subprocess
from pathlib import Path
from typing import Any

from ..config import DATA_DIR, ROOT
from .loader import DYNAMIC

DATASETS_DIR = DATA_DIR / "datasets"
TRAIN_SCRIPT = ROOT / "agent_os" / "training" / "train_mlx.sh"


def harvest(agent_id: str, limit: int = 500) -> list[dict[str, Any]]:
    """Saca los pares (input, output) verificados del agente desde SQLite.

    Regla: solo runs que terminaron 'completed' y donde ESTE agente completó
    (hay un agent_completed con su input+output y NINGÚN agent_failed suyo
    después). Es el equivalente general a "el Verifier aprobó sin reparar":
    si el run entero fue válido, la salida de cada agente sirve de ejemplo.
    """
    from .. import db

    examples: list[dict[str, Any]] = []
    for row in db.list_runs(limit=limit):
        if row.get("status") != "completed":
            continue
        run = db.get_run(row["id"])
        if not run:
            continue
        failed = {
            e["payload"].get("agent")
            for e in run.get("events", [])
            if e["kind"] == "agent_failed"
        }
        if agent_id in failed:
            continue
        for e in run.get("events", []):
            if e["kind"] != "agent_completed":
                continue
            p = e.get("payload", {})
            if p.get("agent") != agent_id:
                continue
            inp, out = p.get("input"), p.get("output")
            if inp and out:
                examples.append({"input": inp, "output": out})
    return examples


def build_dataset(agent_id: str, limit: int = 500, *, compact: bool = True) -> tuple[Path, int]:
    """Genera data/datasets/<agent_id>.jsonl en formato chat mlx-lm.

    Reproduce el system + user EXACTOS de producción para no entrenar fuera de
    distribución. Con `compact=True` el alumno aprende el protocolo glyph: prompt
    de sistema corto + salida con claves compactas → mucho menos cómputo por
    llamada en producción. Devuelve (ruta, nº de ejemplos)."""
    from ..core.glyph import compress, legend

    agent = DYNAMIC.get(agent_id)
    if agent is None:
        raise ValueError(f"agente '{agent_id}' no está en el registro dinámico")
    schema_fields = list(getattr(agent, "_schema_fields", []))

    if compact:
        # El especialista NO necesita el prompt largo: su tarea vive en los pesos.
        # System mínimo + protocolo glyph enseñado en cada ejemplo.
        system = (
            f"{agent.contract.description or agent.contract.name}. "
            f"Devuelve SOLO JSON con claves: {legend(schema_fields)}."
        )
    else:
        system = agent.system_prompt

    examples = harvest(agent_id, limit=limit)
    DATASETS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATASETS_DIR / f"{agent_id}.jsonl"
    n = 0
    with out_path.open("w", encoding="utf-8") as f:
        for ex in examples:
            # build_user_prompt espera un ctx {clave: valor}: usamos el input real.
            user = agent.build_user_prompt(ex["input"])
            out_payload = compress(ex["output"], schema_fields) if compact else ex["output"]
            assistant = json.dumps(out_payload, ensure_ascii=False)
            row = {
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": assistant},
                ]
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return out_path, n


def train(
    agent_id: str,
    version: str = "v1",
    *,
    force: bool = False,
    iters: int | None = None,
) -> dict[str, Any]:
    """Lanza el fine-tune LoRA (bloqueante: minutos). Devuelve el resultado.

    Requiere el dataset ya generado. `force=True` salta el guard de mínimo de
    ejemplos y `iters` acorta el entrenamiento (ambos solo para pruebas de humo)."""
    dataset = DATASETS_DIR / f"{agent_id}.jsonl"
    if not dataset.exists():
        return {"ok": False, "error": f"no hay dataset: corre build_dataset('{agent_id}') primero"}
    import os

    extra_env: dict[str, str] = {}
    if force:
        extra_env["FORCE"] = "1"
    if iters:
        extra_env["ITERS"] = str(iters)

    proc = subprocess.run(
        ["/bin/zsh", str(TRAIN_SCRIPT), agent_id, version, str(dataset)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, **extra_env},
    )
    published = f"agent-os/{agent_id.replace('_', '-')}:{version}"
    ok = proc.returncode == 0
    return {
        "ok": ok,
        "published": published if ok else "",
        "stdout": proc.stdout[-2000:],
        "stderr": proc.stderr[-2000:],
    }


def promote(agent_id: str, model: str, *, compact: bool = True) -> dict[str, Any]:
    """Registra el alumno en models.json → resolve_model lo usa en el próximo run.

    Si `compact`, activa el protocolo glyph en el spec persistido: el agente
    hablará el lenguaje compacto que su modelo aprendió (menos cómputo/llamada).
    """
    from .entrenador import MODELS_FILE

    try:
        mapping = json.loads(MODELS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        mapping = {}
    mapping[agent_id] = model
    MODELS_FILE.parent.mkdir(parents=True, exist_ok=True)
    MODELS_FILE.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")

    if compact:
        spec_path = DATA_DIR / "specs" / f"{agent_id}.json"
        try:
            from .spec import AgentSpec
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            spec["compact_protocol"] = True
            spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
            # Refresca el agente en el registro vivo para que hable glyph ya.
            DYNAMIC.register(AgentSpec.model_validate(spec), persist=False)
        except (FileNotFoundError, json.JSONDecodeError, Exception):
            pass
    return {"ok": True, "agent": agent_id, "model": model, "compact": compact}


async def evaluate(agent_id: str, model: str, holdout: list[dict[str, Any]]) -> dict[str, Any]:
    """Corre `model` sobre ejemplos held-out y puntúa cuántas salidas VALIDAN
    contra el contrato del agente. Es el 'Judge' que decide si una versión sirve.

    Métrica honesta y barata: pass_rate = fracción de salidas que parsean y
    cumplen el output_schema. No mide 'creatividad' (no se puede sin humano),
    pero sí fiabilidad estructural — que es lo que degrada al reentrenar mal.
    """
    from ..core.glyph import expand
    from ..ollama import chat_json

    agent = DYNAMIC.get(agent_id)
    if agent is None or not holdout:
        return {"model": model, "pass_rate": 0.0, "n": 0}

    schema_fields = list(getattr(agent, "_schema_fields", []))
    compact = bool(getattr(agent.spec, "compact_protocol", False))
    passed = 0
    for ex in holdout:
        user = agent.build_user_prompt(ex["input"])
        system = agent.system_prompt if not compact else (
            f"{agent.contract.description or agent.contract.name}. Devuelve SOLO JSON."
        )
        try:
            raw = await chat_json(model, system, user)
            if compact and isinstance(raw, dict):
                raw = expand(raw, schema_fields)
            agent.contract.output_model.model_validate(raw)
            passed += 1
        except Exception:
            pass
    return {"model": model, "pass_rate": round(passed / len(holdout), 3), "n": len(holdout)}


async def metabolize(
    agent_id: str,
    version: str,
    *,
    holdout_k: int = 15,
    min_gain: float = 0.0,
) -> dict[str, Any]:
    """Ciclo completo con EVAL GATE (protección anti-degradación):

      cosecha → separa holdout → entrena candidato → evalúa candidato vs modelo
      actual sobre el holdout → promueve SOLO si el candidato no empeora.

    Devuelve el veredicto. NO promueve a ciegas: éste es el guardarraíl que la
    investigación de agentes lifelong señala como imprescindible (evitar la
    deriva/olvido al auto-mejorarse).
    """
    from .entrenador import MODELS_FILE

    ready = readiness(agent_id)
    if not ready["ready"]:
        return {"ok": False, "stage": "readiness", **ready}

    all_ex = harvest(agent_id)
    holdout = all_ex[-holdout_k:] if len(all_ex) > holdout_k else all_ex[:1]

    # Modelo actual (alumno promocionado o el genérico por defecto).
    try:
        current_model = json.loads(MODELS_FILE.read_text(encoding="utf-8")).get(agent_id)
    except (FileNotFoundError, json.JSONDecodeError):
        current_model = None

    # Entrena el candidato con TODO (el holdout es pequeño; en producción real
    # se excluiría del train — aquí prima demostrar el gate).
    build_dataset(agent_id)
    train_res = await asyncio.to_thread(train, agent_id, version)
    if not train_res.get("ok"):
        return {"ok": False, "stage": "train", **train_res}
    candidate_model = train_res["published"]

    cand_eval = await evaluate(agent_id, candidate_model, holdout)
    base_eval = (
        await evaluate(agent_id, current_model, holdout)
        if current_model else {"pass_rate": 0.0, "model": "(ninguno)"}
    )

    promote_it = cand_eval["pass_rate"] >= base_eval["pass_rate"] + min_gain
    verdict = {
        "ok": True,
        "agent": agent_id,
        "candidate": cand_eval,
        "current": base_eval,
        "promoted": promote_it,
    }
    if promote_it:
        promote(agent_id, candidate_model)
        verdict["detail"] = f"promovido: {cand_eval['pass_rate']} ≥ {base_eval['pass_rate']}"
    else:
        verdict["detail"] = (
            f"RECHAZADO por el gate: candidato {cand_eval['pass_rate']} < "
            f"actual {base_eval['pass_rate']} — se conserva el modelo previo"
        )
    return verdict


def readiness(agent_id: str, min_examples: int = 100) -> dict[str, Any]:
    """Cuántos ejemplos verificados tiene el agente y si ya puede entrenar."""
    n = len(harvest(agent_id))
    return {
        "agent": agent_id,
        "examples": n,
        "min_examples": min_examples,
        "ready": n >= min_examples,
        "faltan": max(0, min_examples - n),
    }
