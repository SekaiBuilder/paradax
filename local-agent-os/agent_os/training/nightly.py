from __future__ import annotations

"""Entrenamiento nocturno de los agentes columna vertebral (1:00 → 7:00).

Maestro: por defecto el 30B LOCAL de Ollama (gratis, sin tokens de nadie).
Con PARADAX_TEACHER="9r/<modelo>" usa un modelo abierto vía 9router.
Alumnos: LoRA (train_mlx.sh) publicados en Ollama.

Agentes (PARADAX_NIGHTLY_AGENTS, separados por comas; por defecto "generalist"):
    generalist      la cadena del Project Manager: Team Planner → Skills
                    Definer → Constructor + Validador. Un spec del Constructor
                    solo entra al dataset si el Validador lo aprueba. Base
                    Qwen3-4B (PARADAX_GENERALIST_BASE=qwen2.5-7b para volver al
                    7B; el Qwen2.5-3B se quedaba corto para planificar equipos).
    action_planner  pipeline REAL (Playwright + Verifier), cosechado por
                    dataset_builder; se evalúa y promociona solo si aprueba.
    script_writer   guion de voz validado por su contrato.

Fases dentro de la ventana:
    1. Generación hasta GEN_UNTIL (3:30). Los datasets se ACUMULAN noche tras
       noche en data/datasets/<agente>.jsonl.
    2. Entrenamiento hasta TRAIN_DEADLINE (6:45): un LoRA por agente con
       ejemplos suficientes. Salvo action_planner, nada se promociona solo:
       se compara antes con el maestro.

Uso:
    .venv/bin/python -m agent_os.training.nightly                 # ventana completa
    .venv/bin/python -m agent_os.training.nightly --smoke         # 1 ronda, sin entrenar
"""

import argparse
import asyncio
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any

import httpx

from ..config import DATA_DIR, NINEROUTER_BASE_URL, ROOT
from ..core import agent as agent_core
from ..ollama import _router_headers, ensure_only_model, list_models, router_model_name

TEACHER = os.getenv("PARADAX_TEACHER", "qwen3-coder:30b")
AGENTS = [a.strip() for a in os.getenv("PARADAX_NIGHTLY_AGENTS", "generalist").split(",") if a.strip()]
# Bases 4-bit en bf16, convertidas en local (mlx_lm convert -q --q-bits 4 --dtype bfloat16).
# Las de mlx-community están en fp16 y el LoRA se va a NaN hacia la iteración 100.
# PARADAX_GENERALIST_BASE acepta un nombre de esta tabla o una ruta a otra base.
STUDENT_BASES = {
    "qwen2.5-7b": ROOT / "training" / "base" / "qwen2.5-7b-instruct-4bit-bf16",
    # Qwen3-4B-Instruct-2507: ~4B activos por token frente a los 7B del denso y
    # los ~3B del maestro MoE (30B-A3B). El 7B nunca podía ganarle en latencia.
    "qwen3-4b": ROOT / "training" / "base" / "qwen3-4b-instruct-2507-4bit-bf16",
}
DEFAULT_STUDENT_BASE = "qwen3-4b"


def student_base(choice: str | None = None) -> str:
    choice = choice if choice is not None else os.getenv("PARADAX_GENERALIST_BASE", DEFAULT_STUDENT_BASE)
    return str(STUDENT_BASES.get(choice, choice))


GENERALIST_BASE = student_base()
GEN_UNTIL = dtime.fromisoformat(os.getenv("PARADAX_GEN_UNTIL", "03:30"))
TRAIN_DEADLINE = dtime.fromisoformat(os.getenv("PARADAX_TRAIN_DEADLINE", "06:45"))
MIN_EXAMPLES = int(os.getenv("MIN_EXAMPLES", "100"))
DATASETS = DATA_DIR / "datasets"
LOG_DIR = ROOT / "runs" / "nightly"

# Orden = prioridad de entrenamiento: el Constructor primero.
GENERALIST = ("constructor", "team_planner", "skills_definer")

LANGS = ["es", "en", "it"]
SCRIPT_REQUESTS = [
    "haz un reel del kanji {k}", "reel corto sobre el kanji {k} para principiantes",
    "vídeo de las flashcards de hiragana", "reel del quiz de katakana",
    "make a reel about the kanji {k}", "reel mostrando la tabla de hiragana",
    "short video explaining the kanji {k} and its reading",
]
GOALS = [
    "Un sistema que vigile ofertas de trabajo en Europa, las puntúe según mi perfil y me prepare la carta",
    "Publicar cada día un post en Instagram sobre japonés con imagen, texto y hashtags",
    "Auditar la seguridad de mi red doméstica y proponer reglas de firewall",
    "Responder emails de clientes de una tienda online clasificándolos por urgencia",
    "Resumir cada mañana las noticias de IA y mandarme un informe corto",
    "Planificar mis estudios de japonés N4 con repasos espaciados y quizzes",
    "Gestionar las facturas de un autónomo: extraer datos, categorizar y avisar vencimientos",
    "Crear guiones y miniaturas para un canal de YouTube de tecnología",
    "Analizar reseñas de un restaurante y proponer mejoras concretas",
    "Monitorizar precios de vuelos Roma-Tokio y avisar cuando bajen",
    "Preparar entrevistas técnicas de Python con preguntas y feedback",
    "Traducir y adaptar la web de un producto al inglés y al italiano",
    "Organizar un evento: invitados, presupuesto, proveedores y calendario",
    "Revisar pull requests de un repo y señalar riesgos de seguridad",
    "Llevar el control de gastos personales y sugerir un presupuesto mensual",
    "Generar fichas de producto para un e-commerce de cerámica artesanal",
    "Investigar competidores de una app y resumir sus precios y funciones",
    "Convertir apuntes de clase en flashcards y un examen de práctica",
    "Coordinar la limpieza y check-in de un apartamento turístico",
    "Detectar tendencias en TikTok de un nicho y proponer ideas de vídeo",
]

# Ejemplos del Constructor retenidos hasta que el Validador decida.
_PENDING: list[dict[str, Any]] = []


def _now() -> dtime:
    return datetime.now().time()


def _before(limit: dtime) -> bool:
    # La ventana empieza a la 1:00, así que "antes de" nunca cruza medianoche.
    return _now() < limit


def _log(msg: str) -> None:
    print(f"{datetime.now():%H:%M:%S} {msg}", flush=True)


def _write(agent_id: str, row: dict[str, Any]) -> None:
    DATASETS.mkdir(parents=True, exist_ok=True)
    with open(DATASETS / f"{agent_id}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _sink(agent_id: str, system: str, user: str, output: dict[str, Any], source: str) -> None:
    if agent_id not in GENERALIST + ("script_writer",):
        return
    output = {k: v for k, v in output.items() if k != "source"}
    row = {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": json.dumps(output, ensure_ascii=False)},
    ], "meta": {"teacher": TEACHER, "source": source, "ts": time.time()}}
    if agent_id == "constructor":
        _PENDING.append(row)  # espera al Validador
    else:
        _write(agent_id, row)


async def check_teacher() -> None:
    """Falla pronto y claro si el maestro no está disponible."""
    if not TEACHER.startswith("9r/"):
        if TEACHER not in await list_models():
            raise RuntimeError(f"Ollama no tiene el maestro {TEACHER!r}")
        return
    name = router_model_name(TEACHER)
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{NINEROUTER_BASE_URL}/models", headers=_router_headers())
        resp.raise_for_status()
    ids = {m.get("id") for m in resp.json().get("data", [])}
    if ids and name not in ids:
        raise RuntimeError(f"9router no ofrece {name!r}")


def _free_ram_gb() -> float:
    """RAM recuperable (libre + inactiva + especulativa) según vm_stat."""
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
        page = int(out.split("page size of ")[1].split()[0])
        pages = 0
        for line in out.splitlines():
            if line.startswith(("Pages free", "Pages inactive", "Pages speculative")):
                pages += int(line.split(":")[1].strip().rstrip("."))
        return pages * page / 1024**3
    except Exception:
        return -1.0


async def lighten() -> None:
    """Modo ligero: solo el maestro ocupa memoria. Descarga cualquier otro
    modelo de Ollama y avisa si no queda sitio para el 30B (~18 GB)."""
    if not TEACHER.startswith("9r/"):
        await ensure_only_model(TEACHER)
        await asyncio.sleep(3)
    free = _free_ram_gb()
    _log(f"RAM recuperable: {free:.1f} GB")
    if 0 <= free < 20 and not TEACHER.startswith("9r/"):
        _log("⚠ poca RAM para el 30B: cierra apps pesadas o la noche irá lenta (swap)")


async def gen_generalist(rng: random.Random) -> str:
    """Una pasada completa del generalista sobre un objetivo, como hace el
    ProjectManager, pero sin registrar agentes ni guardar proyectos."""
    from ..factory.factory import AgentFactory
    from ..factory.project_manager import _enrich
    from ..factory.skills_definer import SkillsDefinerAgent
    from ..factory.team_planner import TeamPlannerAgent
    goal = rng.choice(GOALS)
    factory = AgentFactory()
    plan = await TeamPlannerAgent().run({"goal": goal, "model": TEACHER})
    briefs = await SkillsDefinerAgent().run({
        "goal": goal, "team_plan": plan.model_dump(),
        "skills_catalog": factory.skills_catalog(), "model": TEACHER,
    })
    ok = 0
    created: list[str] = []
    for brief in briefs.briefs:
        taken = factory.taken_ids() + created
        _PENDING.clear()
        try:
            spec = await factory.constructor.run({
                "request": _enrich(brief), "skills_catalog": factory.skills_catalog(),
                "taken_ids": taken, "model": TEACHER,
            })
            verdict = await factory.validador.validate(spec, taken)
        except Exception:  # noqa: BLE001 — un encargo malo no tumba la ronda
            continue
        finally:
            pending = list(_PENDING)
            _PENDING.clear()
        if verdict.ok:
            for row in pending:
                _write("constructor", row)
            created.append(spec.id)
            ok += 1
    return f"✓ {len(plan.agents)} agentes, {ok}/{len(briefs.briefs)} specs aprobados · {goal[:60]}"


async def gen_action_planner(rng: random.Random) -> str:
    from ..orchestrator import MediaRunRequest, run_media_manager
    from .generator import make_request
    req = make_request(rng)
    result = await run_media_manager(MediaRunRequest(request=req, model=TEACHER, make_reel=False))
    ok = result.get("verdict", {}).get("ok") and not result.get("repaired")
    return f"{'✓' if ok else '△'} {req}"


async def gen_script_writer(rng: random.Random) -> str:
    from ..agents.script_writer import ScriptWriterAgent
    from .generator import KANJI_N5
    req = rng.choice(SCRIPT_REQUESTS).format(k=rng.choice(KANJI_N5))
    out = await ScriptWriterAgent().run({"request": req, "language": rng.choice(LANGS), "model": TEACHER})
    return f"{'✗ fallback' if str(out.source).startswith('fallback') else '✓'} {req}"


GENERATORS = {
    "generalist": gen_generalist,
    "action_planner": gen_action_planner,
    "script_writer": gen_script_writer,
}


async def generate(smoke: bool) -> None:
    rng = random.Random()
    agent_core.CAPTURE_SINK = _sink
    rounds = 0
    try:
        while smoke or _before(GEN_UNTIL):
            for agent_id in AGENTS:
                try:
                    _log(f"[{agent_id}] {await GENERATORS[agent_id](rng)}")
                except Exception as exc:  # noqa: BLE001 — una ronda mala no para la noche
                    _log(f"[{agent_id}] ✗ {type(exc).__name__}: {str(exc)[:200]}")
            rounds += 1
            if smoke:
                break
    finally:
        agent_core.CAPTURE_SINK = None
    _log(f"generación terminada: {rounds} rondas")


def _count(path: Path) -> int:
    return sum(1 for _ in open(path, encoding="utf-8")) if path.exists() else 0


def _run(cmd: list[str], env: dict[str, str] | None = None) -> bool:
    remaining = (datetime.combine(datetime.now().date(), TRAIN_DEADLINE) - datetime.now()).total_seconds()
    if remaining < 600:
        _log(f"sin tiempo para: {' '.join(cmd[:4])}")
        return False
    _log("$ " + " ".join(cmd))
    try:
        return subprocess.run(cmd, cwd=ROOT, env={**os.environ, **(env or {})}, timeout=remaining).returncode == 0
    except subprocess.TimeoutExpired:
        _log("cortado por la hora límite")
        return False


def train() -> None:
    py, script = sys.executable, str(ROOT / "agent_os" / "training" / "train_mlx.sh")
    version = "n" + datetime.now().strftime("%Y%m%d")

    if "action_planner" in AGENTS:
        _run([py, "-m", "agent_os.training.dataset_builder"])
        if _count(ROOT / "training" / "dataset" / "train.jsonl") >= MIN_EXAMPLES:
            if _run([script, version]):
                _run([py, "-m", "agent_os.training.evaluator",
                      "--model", f"agent-os/action-planner:{version}", "--promote"])
        else:
            _log("action_planner: pocos ejemplos, no se entrena hoy")

    to_train = (list(GENERALIST) if "generalist" in AGENTS else []) + (
        ["script_writer"] if "script_writer" in AGENTS else [])
    for agent_id in to_train:
        path = DATASETS / f"{agent_id}.jsonl"
        if path.exists():
            from .cheat import audit_dataset
            audited = DATASETS / f"{agent_id}.audited.jsonl"
            kept, dropped = audit_dataset(agent_id, path, audited)
            _log(f"{agent_id}: auditoría del dataset · {kept} limpios"
                 + (f" · descartados {dropped}" if dropped else ""))
            path = audited
        n = _count(path)
        if n < MIN_EXAMPLES:
            _log(f"{agent_id}: {n}/{MIN_EXAMPLES} ejemplos, no se entrena hoy")
            continue
        env = {"BASE_MODEL": GENERALIST_BASE} if agent_id in GENERALIST else None
        # Publicado como agent-os/<agente>:<versión>, sin promoción automática.
        _run([script, agent_id, version, str(path)], env)

    if "generalist" in AGENTS:
        # Mide cada versión contra el maestro y poda las que no aportan.
        _run([py, "-m", "agent_os.training.generalist_eval"])
        # Examen graduado del constructor de esta noche (si no quedó vetado).
        # Con media ≥ PARADAX_REVIEW_FROM pasa a la revisión con Claude.
        from .quarantine import is_vetoed
        tonight = f"agent-os/constructor:{version}"
        if tonight in subprocess.run(["ollama", "list"], capture_output=True, text=True).stdout and not is_vetoed(tonight):
            _run([py, "-m", "agent_os.training.graded_exam", "--model", tonight])


CODE_GLOBS = ("agent_os/**/*.py", "agent_os/**/*.md", "agent_os/**/*.sh", "scripts/*", "tests/*.py")


def code_snapshot() -> dict[str, str]:
    """Huella (sha256) de todo el código fuente. Si cambia durante la noche,
    algo lo modificó: nadie debería tocar el código mientras se entrena."""
    import hashlib
    snap = {}
    for pattern in CODE_GLOBS:
        for path in ROOT.glob(pattern):
            if path.is_file() and "__pycache__" not in path.parts:
                snap[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snap


def code_changes(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    return {
        "modificados": sorted(f for f in before.keys() & after.keys() if before[f] != after[f]),
        "nuevos": sorted(after.keys() - before.keys()),
        "borrados": sorted(before.keys() - after.keys()),
    }


async def main_async(args: argparse.Namespace) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # El maestro manda aunque haya alumnos promocionados en models.json.
    os.environ["PARADAX_TEACHER_MODE"] = "1"
    _log(f"maestro {TEACHER} · agentes {AGENTS}")
    night = datetime.now().strftime("%Y%m%d")
    before = code_snapshot()
    await check_teacher()
    await lighten()
    await generate(args.smoke)
    if not args.smoke and not args.no_train:
        train()
    changes = code_changes(before, code_snapshot())
    (LOG_DIR / f"code-{night}.json").write_text(json.dumps(changes, ensure_ascii=False, indent=1), encoding="utf-8")
    if any(changes.values()):
        _log(f"⚠ el código cambió durante la noche: {changes}")
    if not args.smoke:
        from .morning_report import write_report
        write_report(night)
    _log("noche terminada")


def main() -> None:
    parser = argparse.ArgumentParser(description="Entrenamiento nocturno de los agentes columna vertebral")
    parser.add_argument("--smoke", action="store_true", help="1 ronda, sin entrenar")
    parser.add_argument("--no-train", action="store_true")
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
