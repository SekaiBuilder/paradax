from __future__ import annotations

"""Evaluador de promoción: decide si un modelo alumno entra en producción.

Para cada caso de validación le pide al candidato un plan compacto y lo puntúa
con checks deterministas — los mismos criterios que el pipeline exige en
producción. Nada de jueces LLM opinando: o cumple el contrato o no.

Checks por caso:
    parses        la salida es JSON válido
    wire          decode_plan lo acepta (protocolo compacto bien formado)
    prefix        empieza cerrando popups y tiene 'marcar'
    selectors     todos los selectores existen (inventario real + whitelist)
    waits         esperas dentro de [200, 8000] ms
    tail          termina mostrando el resultado (espera final >= 1000 ms)
    names         nombres de archivo ASCII con extensión correcta

Promoción: score medio >= umbral Y casos perfectos >= umbral. Con --promote
escribe data/models.json — el mapa agente→modelo que producción consultará.

Uso:
    python -m agent_os.training.evaluator --model agent-os/action-planner:v1
    python -m agent_os.training.evaluator --model ... --baseline qwen3-coder:30b
    python -m agent_os.training.evaluator --model ... --promote
"""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from ..agents.action_planner import _selector_allowed
from ..config import DATA_DIR, ROOT
from ..core.wire import WireError, decode_plan
from ..ollama import chat_json
from .dataset_builder import DATASET_DIR, STUDENT_PROMPT

MODELS_FILE = DATA_DIR / "models.json"
CASES_FILE = DATASET_DIR / "valid_cases.jsonl"

PROMOTE_MIN_SCORE = 0.95   # media de checks aprobados
PROMOTE_MIN_PERFECT = 0.80  # fracción de casos con todos los checks en verde


def score_plan(compact: dict[str, Any], inventory: dict[str, Any]) -> dict[str, bool]:
    checks = {"parses": True, "wire": False, "prefix": False, "selectors": False,
              "waits": False, "tail": False, "names": False}
    try:
        plan = decode_plan(compact)
    except (WireError, TypeError, KeyError):
        return checks
    checks["wire"] = True

    actions = plan["actions"]
    kinds = [a.get("accion") for a in actions]
    checks["prefix"] = kinds[0] == "esperar" and "marcar" in kinds[:8]

    selectors = [a["selector"] for a in actions if a.get("selector")]
    checks["selectors"] = all(_selector_allowed(s, inventory) for s in selectors)

    waits = [int(a.get("ms") or 0) for a in actions if a.get("accion") == "esperar"]
    checks["waits"] = bool(waits) and all(200 <= w <= 8000 for w in waits)
    checks["tail"] = bool(actions) and actions[-1].get("accion") == "esperar" and int(actions[-1].get("ms") or 0) >= 1000

    f, g = plan["actions_file_name"], plan["gif_output_name"]
    checks["names"] = (
        f.endswith(".json") and g.endswith(".gif") and f.isascii() and g.isascii()
    )
    return checks


async def evaluate_model(model: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    from .dataset_builder import to_chat  # construye el user igual que producción

    results = []
    for case in cases:
        user = to_chat(case)["messages"][1]["content"]
        try:
            raw = await chat_json(model, STUDENT_PROMPT, user)
            checks = score_plan(raw, case["inventory"])
        except Exception:
            checks = {k: False for k in ("parses", "wire", "prefix", "selectors", "waits", "tail", "names")}
        results.append({"request": case["request"], "checks": checks})

    per_case = [sum(r["checks"].values()) / len(r["checks"]) for r in results]
    return {
        "model": model,
        "cases": len(results),
        "score": round(sum(per_case) / len(per_case), 4) if per_case else 0.0,
        "perfect": round(sum(1 for s in per_case if s == 1.0) / len(per_case), 4) if per_case else 0.0,
        "failures": [
            {"request": r["request"], "failed": [k for k, v in r["checks"].items() if not v]}
            for r in results
            if not all(r["checks"].values())
        ][:20],
    }


def should_promote(report: dict[str, Any]) -> bool:
    return report["score"] >= PROMOTE_MIN_SCORE and report["perfect"] >= PROMOTE_MIN_PERFECT


def promote(agent_id: str, model: str) -> None:
    current = json.loads(MODELS_FILE.read_text(encoding="utf-8")) if MODELS_FILE.exists() else {}
    current[agent_id] = model
    MODELS_FILE.parent.mkdir(parents=True, exist_ok=True)
    MODELS_FILE.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def load_cases(path: Path = CASES_FILE) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"No hay casos en {path}. Corre primero el dataset_builder.")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


async def main_async(args: argparse.Namespace) -> None:
    cases = load_cases(Path(args.cases))
    report = await evaluate_model(args.model, cases)
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.baseline:
        base = await evaluate_model(args.baseline, cases)
        print(json.dumps(base, ensure_ascii=False, indent=2))
        verdict = "GANA el candidato" if report["score"] >= base["score"] else "gana el baseline"
        print(f"candidato {report['score']} vs baseline {base['score']} → {verdict}")

    if should_promote(report):
        print(f"APTO para promoción (score {report['score']}, perfectos {report['perfect']})")
        if args.promote:
            promote("action_planner", args.model)
            print(f"Promocionado: action_planner → {args.model} en {MODELS_FILE}")
    else:
        print(
            f"NO apto: score {report['score']} (mín {PROMOTE_MIN_SCORE}), "
            f"perfectos {report['perfect']} (mín {PROMOTE_MIN_PERFECT})"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evalúa un modelo candidato para Action Planner")
    parser.add_argument("--model", required=True, help="modelo Ollama candidato")
    parser.add_argument("--baseline", help="modelo de referencia para comparar (p. ej. el maestro)")
    parser.add_argument("--cases", default=str(CASES_FILE))
    parser.add_argument("--promote", action="store_true", help="escribe data/models.json si es apto")
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
