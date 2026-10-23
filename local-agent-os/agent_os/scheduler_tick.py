from __future__ import annotations

"""Tick del smart scheduler para launchd.

Corre los proyectos cuyo horario inteligente coincide AHORA. Un smart schedule
no guarda "la hora a la que empezar" sino el DEADLINE (hora de finalización); el
momento de disparo se calcula como `deadline - duración_estimada`, usando el
historial real de duraciones (DurationTracker). Así la tarea TERMINA a tiempo.

Pensado para ejecutarse cada 60s desde un LaunchAgent — funciona **aunque la
app/servidor esté cerrado**, porque ejecuta el pipeline directamente (no por HTTP).

Barato cuando no hay nada que disparar: lee smart_schedules.json y, si no toca
nada, sale antes de importar lo pesado.

Uso:
    python -m agent_os.scheduler_tick            # dispara lo que toque ahora
    python -m agent_os.scheduler_tick --dry-run  # solo reporta, no ejecuta
"""

import argparse
import asyncio
import sys
from datetime import datetime

from .automation import smart_scheduler
from .automation.duration_tracker import DurationTracker


def main() -> None:
    ap = argparse.ArgumentParser(description="Tick del smart scheduler (launchd)")
    ap.add_argument("--dry-run", action="store_true", help="solo reporta lo que dispararía")
    args = ap.parse_args()

    now = datetime.now()
    tracker = DurationTracker()
    items = smart_scheduler._load()
    due = [s for s in items if smart_scheduler.should_fire(s, now, tracker)]
    if not due:
        return  # nada que hacer → salida rápida (esto corre cada minuto)

    if args.dry_run:
        for s in due:
            print(
                f"DUE  {s['id']}  project={s['project_id']}  "
                f"deadline={s['deadline_time']}  @ {now:%Y-%m-%d %H:%M}"
            )
        return

    # Marca last_fired ANTES de correr: evita doble disparo si el tick se solapa
    # con el loop in-process de la app o con el siguiente tick.
    stamp = now.strftime("%Y-%m-%d %H:%M")
    due_ids = {s["id"] for s in due}
    for s in items:
        if s["id"] in due_ids:
            s["last_fired"] = stamp
    smart_scheduler._save(items)

    # Imports pesados solo cuando de verdad hay que correr algo.
    from . import project_runner
    from .factory.loader import DYNAMIC
    from .factory.project import ProjectStore

    DYNAMIC.load_all()
    store = ProjectStore()
    for s in due:
        project = store.get(s["project_id"])
        if not project:
            print(f"SKIP proyecto inexistente: {s['project_id']}", file=sys.stderr)
            continue
        try:
            asyncio.run(
                project_runner.run_project(
                    project,
                    schedule_id=s["id"],
                    deadline_time=s.get("deadline_time", ""),
                )
            )
            print(f"RAN  {s['project_id']}  ({s['id']})  @ {stamp}")
        except Exception as exc:
            print(f"FAIL {s['project_id']}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
