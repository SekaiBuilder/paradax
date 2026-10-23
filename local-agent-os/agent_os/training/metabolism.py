from __future__ import annotations

"""Metabolismo: el organismo se re-entrena SOLO cuando la experiencia nueva lo
justifica, y nunca promueve una versión peor (eval gate).

Cierra el lazo de vida de Paradax:
    Proposer (genera tareas donde el agente es débil)
        → runs verificados (experiencia)
        → distill_with_gate (candidato + holdout eval)
        → promueve SOLO si no empeora
        → repite

Uso:
    # revisa TODOS los agentes construidos y metaboliza los elegibles
    .venv/bin/python -m agent_os.training.metabolism

    # solo los de un proyecto, con umbral de experiencia nueva
    .venv/bin/python -m agent_os.training.metabolism --project firewall-y-adblock --min-new 30

Elegibilidad: un agente entra al ciclo si tiene >= min_examples ejemplos
verificados Y acumuló al menos --min-new desde su última versión (para no
re-entrenar por 1 ejemplo nuevo). El estado por agente se guarda en
data/metabolism_state.json.
"""

import argparse
import asyncio
import json
import sys
import time
from typing import Any

from ..config import DATA_DIR
from ..factory import distill_agent

STATE_FILE = DATA_DIR / "metabolism_state.json"


def _load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _agent_ids(project: str | None) -> list[str]:
    from ..factory.loader import DYNAMIC

    ids = []
    for agent in DYNAMIC.all():
        spec = getattr(agent, "spec", None)
        if spec is None or not getattr(spec, "uses_llm", True):
            continue
        if project and getattr(spec, "project", "") != project:
            continue
        ids.append(agent.contract.id)
    return ids


async def cycle(
    *,
    project: str | None = None,
    min_new: int = 25,
    min_examples: int = 100,
) -> list[dict[str, Any]]:
    """Un tick del metabolismo: metaboliza los agentes elegibles. Devuelve el
    veredicto por agente (promovido / rechazado por el gate / no elegible)."""
    from ..factory.loader import DYNAMIC

    DYNAMIC.load_all()
    state = _load_state()
    results: list[dict[str, Any]] = []

    for aid in _agent_ids(project):
        n = len(distill_agent.harvest(aid))
        last = state.get(aid, {})
        trained_at = last.get("examples_at_train", 0)
        new_since = n - trained_at

        if n < min_examples:
            results.append({"agent": aid, "skipped": f"solo {n}/{min_examples} ejemplos"})
            continue
        if new_since < min_new and last.get("version"):
            results.append({"agent": aid, "skipped": f"solo {new_since} ejemplos nuevos (<{min_new})"})
            continue

        version = f"v{last.get('n_versions', 0) + 1}"
        print(f"── metabolizando {aid} → {version} ({n} ejemplos, {new_since} nuevos)", flush=True)
        verdict = await distill_agent.metabolize(aid, version)
        verdict["agent"] = aid

        if verdict.get("ok"):
            state[aid] = {
                "n_versions": last.get("n_versions", 0) + 1,
                "version": version,
                "examples_at_train": n,
                "promoted": verdict.get("promoted"),
                "at": time.strftime("%Y-%m-%d %H:%M"),
            }
            _save_state(state)
        results.append(verdict)
        print(f"   {verdict.get('detail', verdict)}", flush=True)

    return results


def main() -> None:
    ap = argparse.ArgumentParser(description="Metabolismo: re-entreno con eval gate")
    ap.add_argument("--project", default=None, help="limita a los agentes de un proyecto")
    ap.add_argument("--min-new", type=int, default=25, help="ejemplos nuevos mínimos para re-entrenar")
    ap.add_argument("--min-examples", type=int, default=100)
    args = ap.parse_args()

    results = asyncio.run(
        cycle(project=args.project, min_new=args.min_new, min_examples=args.min_examples)
    )
    promoted = sum(1 for r in results if r.get("promoted"))
    rejected = sum(1 for r in results if r.get("ok") and not r.get("promoted"))
    skipped = sum(1 for r in results if r.get("skipped"))
    print(
        f"\nMETABOLISMO: {promoted} promovidos, {rejected} rechazados por el gate, "
        f"{skipped} sin cambios",
        flush=True,
    )
    if not results:
        sys.exit(0)


if __name__ == "__main__":
    main()
