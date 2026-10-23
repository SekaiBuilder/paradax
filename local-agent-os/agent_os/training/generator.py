from __future__ import annotations

"""Generador de dataset: fabrica runs verificados mientras duermes.

Bucle: pedido variado (plantilla × kanji/sección/idioma) → pipeline REAL
(maestro 30B planifica, Playwright graba, Verifier juzga) → el run queda en
SQLite. Después `dataset_builder` cosecha solo los aprobados.

No genera reels (make_reel=False): el plan + GIF verificado es lo que entrena
al alumno; el reel solo añadiría minutos de TTS/FFmpeg por run.

Uso:
    python -m agent_os.training.generator --rounds 40
    python -m agent_os.training.generator --rounds 200 --sleep 5
"""

import argparse
import asyncio
import json
import random
import time

from ..orchestrator import MediaRunRequest, run_media_manager

# Los 52 kanji EXACTOS de la tabla básica visible (volcados del DOM real con
# Playwright tras abrir #btn-kanji). El bundle trae 103, pero solo estos son
# clicables sin abrir el modal "Tabla completa" — un kanji fuera de esta lista
# garantiza un paso fallido y un run que no entrena.
KANJI_N5 = list(
    "一二三四五六七八九十百千万円日月火水木金土年時分半今毎週午前後"
    "人男女子父母友口目耳手足力文門間入出立空名"
)

TEMPLATES = [
    "haz un gif del kanji {k}",
    "quiero un gif mostrando el kanji {k} en la página real",
    "crea un gif de la ficha del kanji {k}",
    "gif del 漢字 {k} usando Kana Trainer",
    "muéstrame el kanji {k} en un gif",
    "make a gif of the kanji {k} on the real page",
    "crea un gif della scheda del kanji {k}",
]

TEMPLATES_GENERAL = [
    "haz un gif de las flashcards de hiragana",
    "crea un gif del modo flashcards de katakana",
    "gif de la tabla completa de hiragana",
    "quiero un gif del quiz de katakana",
    "haz un gif practicando hiragana en la página real",
    "make a gif of the hiragana flashcards",
    "gif del quiz de kanji en la página real",
]


def make_request(rng: random.Random) -> str:
    if rng.random() < 0.7:
        template = rng.choice(TEMPLATES)
        return template.format(k=rng.choice(KANJI_N5))
    return rng.choice(TEMPLATES_GENERAL)


async def generate(rounds: int, sleep_s: float, seed: int | None) -> None:
    rng = random.Random(seed)
    ok = failed = 0
    t0 = time.time()
    for i in range(1, rounds + 1):
        request = make_request(rng)
        print(f"[{i}/{rounds}] {request}", flush=True)
        try:
            result = await run_media_manager(MediaRunRequest(request=request, make_reel=False))
            verdict = result.get("verdict", {})
            repaired = result.get("repaired", False)
            ok += 1
            status = "✓ verificado" if verdict.get("ok") and not repaired else "△ reparado (no entrena)"
            print(f"    {status} · {result['run_id']}", flush=True)
        except Exception as exc:
            failed += 1
            print(f"    ✗ {type(exc).__name__}: {str(exc)[:200]}", flush=True)
        if sleep_s and i < rounds:
            await asyncio.sleep(sleep_s)

    minutes = (time.time() - t0) / 60
    print(json.dumps({"rounds": rounds, "completed": ok, "failed": failed, "minutes": round(minutes, 1)}))
    print("Ahora cosecha con: python -m agent_os.training.dataset_builder")


def main() -> None:
    parser = argparse.ArgumentParser(description="Genera runs verificados para el dataset")
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--sleep", type=float, default=2.0, help="pausa entre runs (s)")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(generate(args.rounds, args.sleep, args.seed))


if __name__ == "__main__":
    main()
