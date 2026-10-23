from __future__ import annotations

"""Generador de experiencia para proyectos: fabrica runs verificados mientras
duermes, con peticiones VARIADAS (si los 100 ejemplos son idénticos, el alumno
memoriza en vez de aprender).

Corre como proceso propio (independiente de la app):

    .venv/bin/python -m agent_os.training.project_generator \
        --project social-media-manager --rounds 120 --model qwen2.5:7b

Cada ronda lanza el pipeline REAL del proyecto con una petición distinta
(tema × tono × plataforma). Cada run completado deja un ejemplo de
entrenamiento por agente (input real → output verificado) listo para
`distill_agent.build_dataset`.

Los agentes de contenido no tienen tools de escritura, así que se desactiva el
snapshot git de seguridad: evita llenar el historial con cientos de commits
de runs sintéticos que no tocan archivos.
"""

import argparse
import asyncio
import random
import sys
import time

TEMAS = [
    "el café de especialidad", "los beneficios de caminar 30 minutos al día",
    "trucos para ahorrar en la compra semanal", "cómo empezar en la fotografía móvil",
    "recetas rápidas para cenas de semana", "la importancia de dormir bien",
    "plantas de interior fáciles de cuidar", "aprender japonés desde cero",
    "rutinas de estiramiento para oficinistas", "los mejores podcasts de historia",
    "cómo organizar un escritorio minimalista", "viajar barato por Europa",
    "el ayuno intermitente explicado simple", "libros cortos para volver a leer",
    "errores comunes al hacer pan casero", "meditación para principiantes",
    "cómo elegir una bicicleta urbana", "apps para controlar gastos",
    "el arte del descanso sin pantallas", "senderismo cerca de la ciudad",
    "batidos verdes que sí saben bien", "fotografía de paisajes al amanecer",
    "cómo cuidar la voz si hablas mucho", "juegos de mesa para dos personas",
    "escribir un diario: por dónde empezar", "queso y vino: maridajes básicos",
    "estiramientos para dolor de espalda", "cómo hacer compost en casa",
    "rutina de skincare minimalista", "el método pomodoro en la práctica",
]
TONOS = ["cercano y motivador", "informativo y directo", "divertido con humor ligero", "inspirador"]
PLATAFORMAS = ["Instagram", "LinkedIn", "X (Twitter)"]


def peticiones(n: int, seed: int = 7) -> list[str]:
    combos = [
        f"redacta un post sobre {t} con tono {tono} para {p}"
        for t in TEMAS for tono in TONOS for p in PLATAFORMAS
    ]
    random.Random(seed).shuffle(combos)
    return combos[:n]


async def main() -> None:
    ap = argparse.ArgumentParser(description="Genera experiencia real para un proyecto")
    ap.add_argument("--project", required=True)
    ap.add_argument("--rounds", type=int, default=120)
    ap.add_argument("--model", default="qwen2.5:7b")
    ap.add_argument("--sleep", type=float, default=3.0, help="pausa entre rondas (s)")
    ap.add_argument("--uniform", action="store_true",
                    help="muestreo plano (desactiva el Proposer adaptativo)")
    args = ap.parse_args()

    from ..factory.loader import DYNAMIC
    from ..factory.project import ProjectStore
    from .. import project_runner

    DYNAMIC.load_all()
    project = ProjectStore().get(args.project)
    if project is None:
        print(f"proyecto no encontrado: {args.project}", file=sys.stderr)
        sys.exit(1)

    # Runs sintéticos de agentes SIN tools de escritura: el snapshot git solo
    # ensuciaría el historial. Se desactiva únicamente en este proceso.
    project_runner._safety_snapshot = lambda msg: ""  # type: ignore[assignment]

    from . import proposer
    from .. import db

    # Multi-Agent Evolve: el Proposer sesga hacia las debilidades aprendidas.
    # (--uniform vuelve al muestreo plano del generador base.)
    if args.uniform:
        combos = [None] * args.rounds
        reqs = peticiones(args.rounds)
    else:
        combos = proposer.propose(args.rounds)
        reqs = [proposer.to_request(c) for c in combos]

    ok = fail = 0
    qsum = 0.0
    t0 = time.time()
    for i, (req, combo) in enumerate(zip(reqs, combos), 1):
        try:
            result = await project_runner.run_project(project, model=args.model, request=req)
            status = result.get("status", "?")
            ok += status == "completed"
            fail += status != "completed"
            # Calidad del run → el Proposer aprende qué tareas son duras.
            q = 1.0
            if combo is not None:
                run = db.get_run(result.get("run_id", "")) or {}
                q = proposer.quality_of_run(run)
                proposer.record(combo, q)
                qsum += q
            el = int(time.time() - t0)
            flag = "" if q >= 0.9 else (" ⚠dura" if q < 0.5 else " ~")
            print(f"[{i}/{len(reqs)}] {status:10s} q={q:.2f}{flag} ok={ok} fail={fail} "
                  f"({el//60}m{el%60:02d}s) — {req[:52]}", flush=True)
        except Exception as exc:  # noqa: BLE001 — una ronda mala no para la noche
            fail += 1
            print(f"[{i}/{len(reqs)}] ERROR: {exc}", flush=True)
        await asyncio.sleep(args.sleep)

    print(f"\nFIN: {ok} completados, {fail} fallidos en {int((time.time()-t0)/60)} min", flush=True)
    if not args.uniform:
        print(f"calidad media: {qsum/max(1,ok):.2f}", flush=True)
        print("debilidades aprendidas (top):", flush=True)
        for r in proposer.report(top=6):
            print(f"  {r['dim']}={r['value']}: debilidad {r['debilidad']} (n={r['n']})", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
