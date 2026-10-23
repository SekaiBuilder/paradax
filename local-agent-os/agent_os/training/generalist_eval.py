from __future__ import annotations

"""Evaluación y retención de los alumnos del generalista.

Cada noche, tras entrenar, se MIDE cada versión de team_planner,
skills_definer y constructor contra casos reservados (objetivos que nunca
entran al dataset) y contra el maestro. Métricas deterministas, sin opinión
de ningún LLM:

    team_planner    valid_first  respuesta válida a la primera (sin reintento)
                    size_ok      equipo de 1 a 6 agentes
                    size_close   tamaño a ±1 del que propone el maestro
    skills_definer  valid_first  válida a la primera (incluye skills/tools reales)
                    coverage     un encargo por cada agente del plan
    constructor     valid        produce un spec (aunque sea con reintento)
                    approved     el Validador lo aprueba
                    first_try    válido a la primera

score = media de sus métricas. En los alumnos se añade `clean` (fracción de
casos sin cuarentena): un caso con reacción rara o trampa baja el score.
Además: latencia media por llamada.

Casos NUEVOS cada noche: el maestro propone objetivos que nunca se usaron
(ni en entrenamiento ni en noches anteriores). Repetir los mismos casos no
aporta información: lo que cuenta son casos INDEPENDIENTES.

Regla de promoción (estadística):
    Un caso cuenta como acierto si pasa TODAS sus métricas y no tiene ninguna
    reacción inesperada. Se lleva la racha de aciertos seguidos por versión.
      · regla del tres: con n aciertos seguidos, la tasa de fallo real es
        ≤ 3/n con un 95 % de confianza.
      · Laplace: P(acertar el siguiente) = (aciertos + 1) / (casos + 2).
    LISTA para promoción con racha ≥ READY_STREAK (60 → fallo ≤ 5 %), sin
    veto, sin fallar más que el maestro y sin ser más lenta que él
    (latencia ≤ maestro × MAX_LATENCY_RATIO): un alumno que no ahorra tiempo
    no aporta nada. Avisa con una notificación de macOS
    y runs/nightly/LISTO-<agente>.txt. Nunca se promociona sola.

Retención: por agente se conservan la de RACHA más larga, la MÁS RECIENTE,
las vetadas (para estudiarlas) y la promocionada; el resto se borra de Ollama.
Las vetadas no se vuelven a examinar: hasta que las liberes no pueden
promocionarse, y examinarlas solo gasta la noche y llena la cuarentena.

Resultados: data/scoreboard.json (histórico) y runs/nightly/scoreboard-AAAAMMDD.md.

Uso:
    .venv/bin/python -m agent_os.training.generalist_eval            # evalúa y aplica retención
    .venv/bin/python -m agent_os.training.generalist_eval --dry-run  # evalúa sin borrar nada
"""

import argparse
import asyncio
import json
import os
import subprocess
import time
from datetime import datetime
from statistics import mean
from typing import Any

from ..config import DATA_DIR, ROOT
from ..core import agent as agent_core

TEACHER = os.getenv("PARADAX_TEACHER", "qwen3-coder:30b")
AGENTS = ("constructor", "team_planner", "skills_definer")
READY_STREAK = int(os.getenv("PARADAX_READY_STREAK", "60"))
MAX_LATENCY_RATIO = float(os.getenv("PARADAX_MAX_LATENCY_RATIO", "1.0"))
N_CASES = 8
EVAL_DIR = DATA_DIR / "eval"
CASES_DIR = EVAL_DIR / "cases"
SEEN_GOALS = EVAL_DIR / "seen_goals.json"
LEGACY_CASES = EVAL_DIR / "generalist_cases.json"
SCOREBOARD = DATA_DIR / "scoreboard.json"
TEACHER_RAW_DIR = EVAL_DIR / "teacher_raw"

# Reservados: NO están en nightly.GOALS, así que el alumno nunca los vio.
HELDOUT_GOALS = [
    "Gestionar las reservas de una clínica dental y recordar citas a los pacientes",
    "Vigilar el stock de una cafetería y proponer pedidos semanales a proveedores",
    "Crear un boletín semanal para una comunidad de corredores con rutas y consejos",
    "Analizar los logs de un servidor web y alertar de patrones sospechosos",
    "Ayudar a un estudiante a escribir su tesis: bibliografía, esquema y revisión",
    "Clasificar fotos de un viaje por lugar y fecha y generar un álbum con textos",
    "Comparar seguros de coche a partir de documentos PDF y recomendar el mejor",
    "Moderar comentarios de un foro detectando spam e insultos",
]


def _version_tags(agent_id: str) -> list[str]:
    """Etiquetas de Ollama de este agente, de la más vieja a la más nueva."""
    out = subprocess.run(["ollama", "list"], capture_output=True, text=True).stdout
    prefix = f"agent-os/{agent_id.replace('_', '-')}:"
    return sorted(line.split()[0] for line in out.splitlines()[1:]
                  if line.split() and line.split()[0].startswith(prefix))


def _promoted() -> dict[str, str]:
    try:
        return json.loads((DATA_DIR / "models.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


class _Sources:
    """Captura la fuente (model / model_retry_N) de cada salida válida."""

    def __init__(self) -> None:
        self.last: dict[str, str] = {}

    def __call__(self, agent_id, system, user, output, source) -> None:  # noqa: ANN001
        self.last[agent_id] = source


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _seen() -> set[str]:
    try:
        return set(json.loads(SEEN_GOALS.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return set()


async def _new_goals(n: int) -> list[str]:
    """Objetivos que nunca se usaron: ni en entrenamiento (nightly.GOALS) ni en
    noches anteriores. Los propone el maestro; si falla, no hay casos hoy."""
    from ..ollama import chat_json
    from .nightly import GOALS
    used = _seen() | {_norm(g) for g in GOALS}
    if not any(_norm(g) in used for g in HELDOUT_GOALS):
        return HELDOUT_GOALS[:n]  # primera noche: la reserva fija
    system = "Respondes solo JSON."
    user = (f"Propón {n * 2} objetivos de proyecto MUY variados (sectores, tamaños y tareas "
            "distintas) que alguien pediría a un sistema que crea equipos de agentes de IA. "
            'Una frase cada uno, en español. Formato: {"goals": ["...", "..."]}')
    raw = await chat_json(TEACHER, system, user)
    goals = []
    for g in raw.get("goals") or []:
        if isinstance(g, str) and 15 < len(g) < 200 and _norm(g) not in used:
            used.add(_norm(g))
            goals.append(g.strip())
    return goals[:n]


async def build_cases(night: str) -> list[dict[str, Any]]:
    """Casos de ESTA noche: objetivos nuevos + plan y encargos del maestro
    (entradas fijas y comparables para todas las versiones)."""
    path = CASES_DIR / f"{night}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    from ..factory.factory import AgentFactory
    from ..factory.skills_definer import SkillsDefinerAgent
    from ..factory.team_planner import TeamPlannerAgent
    factory = AgentFactory()
    goals = await _new_goals(N_CASES)
    if LEGACY_CASES.exists() and goals == HELDOUT_GOALS[:N_CASES]:
        cases = json.loads(LEGACY_CASES.read_text(encoding="utf-8"))  # ya calculados
    else:
        cases = []
        for goal in goals:
            try:
                plan = await TeamPlannerAgent().run({"goal": goal, "model": TEACHER})
                briefs = await SkillsDefinerAgent().run({
                    "goal": goal, "team_plan": plan.model_dump(),
                    "skills_catalog": factory.skills_catalog(), "model": TEACHER,
                })
                cases.append({"goal": goal, "team_plan": plan.model_dump(),
                              "briefs": [b.model_dump() for b in briefs.briefs]})
            except Exception as exc:  # noqa: BLE001
                print(f"  caso descartado ({goal[:40]}…): {exc}")
    CASES_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cases, ensure_ascii=False, indent=1), encoding="utf-8")
    seen = _seen() | {_norm(c["goal"]) for c in cases}
    SEEN_GOALS.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=1), encoding="utf-8")
    return cases


async def evaluate(agent_id: str, model: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    from ..factory.factory import AgentFactory
    from ..factory.project_manager import _enrich
    from ..factory.skills_definer import AgentBrief, SkillsDefinerAgent
    from ..factory.team_planner import TeamPlannerAgent

    factory = AgentFactory()
    sources = _Sources()
    agent_core.CAPTURE_SINK = sources
    # Primera salida CRUDA de cada caso (antes de validar): material del
    # detector de reacciones inesperadas.
    raws: list[dict[str, Any]] = []
    current: dict[str, Any] = {}

    def raw_sink(aid, mdl, user, raw, attempt):  # noqa: ANN001
        if aid == agent_id and attempt == 0 and "raw" not in current:
            current.update(user=user, raw=raw)

    agent_core.RAW_SINK = raw_sink
    metrics: dict[str, list[float]] = {}
    latencies: list[float] = []
    per_case: list[bool] = []
    case_ok = [True]

    def add(name: str, ok: bool) -> None:
        metrics.setdefault(name, []).append(1.0 if ok else 0.0)
        case_ok[0] = case_ok[0] and ok

    try:
        for case in cases:
            sources.last.clear()
            current.clear()
            case_ok[0] = True
            t0 = time.time()
            if agent_id == "team_planner":
                try:
                    plan = await TeamPlannerAgent().run({"goal": case["goal"], "model": model})
                    n, ref = len(plan.agents), len(case["team_plan"]["agents"])
                    add("valid_first", sources.last.get(agent_id) == "model")
                    add("size_ok", 1 <= n <= 6)
                    add("size_close", abs(n - ref) <= 1)
                except Exception:  # noqa: BLE001
                    for m in ("valid_first", "size_ok", "size_close"):
                        add(m, False)
            elif agent_id == "skills_definer":
                try:
                    briefs = await SkillsDefinerAgent().run({
                        "goal": case["goal"], "team_plan": case["team_plan"],
                        "skills_catalog": factory.skills_catalog(), "model": model,
                    })
                    add("valid_first", sources.last.get(agent_id) == "model")
                    add("coverage", len(briefs.briefs) == len(case["team_plan"]["agents"]))
                except Exception:  # noqa: BLE001
                    add("valid_first", False)
                    add("coverage", False)
            else:  # constructor: un encargo por caso (el primero) para acotar el tiempo
                brief = AgentBrief(**case["briefs"][0])
                taken = factory.taken_ids()
                try:
                    spec = await factory.constructor.run({
                        "request": _enrich(brief), "skills_catalog": factory.skills_catalog(),
                        "taken_ids": taken, "model": model,
                    })
                    verdict = await factory.validador.validate(spec, taken)
                    add("valid", True)
                    add("approved", bool(verdict.ok))
                    add("first_try", sources.last.get(agent_id) == "model")
                except Exception:  # noqa: BLE001
                    for m in ("valid", "approved", "first_try"):
                        add(m, False)
            latencies.append(time.time() - t0)
            raws.append(dict(current))
            per_case.append(case_ok[0])
    finally:
        agent_core.CAPTURE_SINK = None
        agent_core.RAW_SINK = None

    summary = {m: round(mean(v), 3) for m, v in metrics.items()}
    return {
        "agent": agent_id, "model": model, "cases": len(cases),
        "metrics": summary,
        "score": round(mean(summary.values()), 3) if summary else 0.0,
        "latency_s": round(mean(latencies), 1) if latencies else None,
        "per_case": per_case,
        "_raws": raws,  # no va al scoreboard
    }


def _contract_keys(agent_id: str) -> set[str]:
    from ..factory.constructor import ConstructorAgent
    from ..factory.skills_definer import SkillsDefinerAgent
    from ..factory.team_planner import TeamPlannerAgent
    cls = {"constructor": ConstructorAgent, "team_planner": TeamPlannerAgent,
           "skills_definer": SkillsDefinerAgent}[agent_id]
    return set(cls.contract.output_model.model_fields)


def scan(agent_id: str, model: str, raws: list[dict[str, Any]], teacher_raws: list[Any],
         cases: list[dict[str, Any]] | None = None) -> dict[int, dict[str, str]]:
    """Detector de reacciones inesperadas + detector de trampas sobre cada
    salida cruda. Lo encontrado va a cuarentena con su categoría.
    Devuelve {índice_de_caso: {"id", "category"}}."""
    from ..factory.factory import AgentFactory
    from ..factory.tool_catalog import all_tools
    from .anomaly import HIGH, detect, worst
    from .cheat import TrainingIndex, detect_cheat
    from .quarantine import store
    skills = {s["id"] for s in AgentFactory().skills_catalog()}
    tools = {t.name for t in all_tools()}
    keys = _contract_keys(agent_id)
    index = TrainingIndex(DATA_DIR / "datasets" / f"{agent_id}.jsonl")
    outputs = [item.get("raw") for item in raws if "raw" in item]
    found: dict[int, dict[str, str]] = {}
    for i, item in enumerate(raws):
        if "raw" not in item:
            continue
        teacher = teacher_raws[i] if i < len(teacher_raws) else None
        task = item.get("user") or ""
        if cases and i < len(cases):
            task = cases[i]["goal"] + " " + task
        signals = detect(agent_id, item["raw"], teacher, allowed_keys=keys,
                         known_skills=skills, known_tools=tools)
        cheats = detect_cheat(agent_id, task, item["raw"], index=index, same_model_outputs=outputs)
        sev = worst(signals)
        if sev == HIGH:
            category = "escape"
        elif cheats:
            category = "trampa"
        elif sev:
            category = "rareza"
        else:
            continue
        cid = store({"agent": agent_id, "model": model, "category": category,
                     "severity": sev or "trampa", "signals": signals + cheats,
                     "user": item["user"], "raw": item["raw"], "teacher_raw": teacher})
        found[i] = {"id": cid, "category": category}
    return found


def _history() -> list[dict[str, Any]]:
    try:
        return json.loads(SCOREBOARD.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def _row(history: list[dict[str, Any]], agent_id: str, model: str, night: str) -> dict[str, Any] | None:
    for row in reversed(history):
        if row["agent"] == agent_id and row["model"] == model and row.get("night") == night:
            return row
    return None


def readiness(history: list[dict[str, Any]], agent_id: str, model: str) -> dict[str, Any]:
    """Estadística acumulada de una versión en casos independientes."""
    rows = sorted((r for r in history if r["agent"] == agent_id and r["model"] == model
                   and "per_case" in r), key=lambda r: r.get("night", ""))
    outcomes = [ok for r in rows for ok in r["per_case"]]
    streak = 0
    for ok in reversed(outcomes):
        if not ok:
            break
        streak += 1
    n, wins = len(outcomes), sum(outcomes)
    return {
        "nights": len(rows), "cases": n, "wins": wins, "streak": streak,
        "laplace": round((wins + 1) / (n + 2), 3),
        "fail_upper_95": round(min(1.0, 3 / streak), 3) if streak else 1.0,
        "fail_rate": round(1 - wins / n, 3) if n else None,
    }


def apply_quarantine(row: dict[str, Any], flagged: dict[int, dict[str, str]]) -> None:
    """Un caso en cuarentena no es acierto (racha) y baja el score vía `clean`."""
    row["quarantine"] = list(flagged.values())
    row["per_case"] = [ok and i not in flagged for i, ok in enumerate(row["per_case"])]
    if row["cases"]:
        row["metrics"]["clean"] = round(1 - len(flagged) / row["cases"], 3)
        row["score"] = round(mean(row["metrics"].values()), 3)


def fast_enough(row: dict[str, Any], teacher: dict[str, Any]) -> bool:
    lat, ref = row.get("latency_s"), teacher.get("latency_s")
    return lat is not None and ref is not None and lat <= ref * MAX_LATENCY_RATIO


def _notify(title: str, text: str) -> None:
    safe = text.replace('"', "'")[:200]
    subprocess.run(["osascript", "-e", f'display notification "{safe}" with title "{title}"'],
                   capture_output=True)


def retention(agent_id: str, rows: list[dict[str, Any]], tags: list[str]) -> tuple[list[str], list[str]]:
    """(conservar, borrar). Conserva la mejor, la más reciente y la promocionada."""
    from .quarantine import is_vetoed, ollama_env
    by_model = {r["model"]: r for r in rows}
    keep = set()
    if tags:
        keep.add(tags[-1])  # la más reciente: aún puede necesitar más noches
        clean = [t for t in tags if not is_vetoed(t)]
        if clean:
            # Mejor = racha más larga en casos independientes; desempate por score.
            keep.add(max(clean, key=lambda t: (by_model.get(t, {}).get("streak", -1),
                                               by_model.get(t, {}).get("score", -1))))
    # Las vetadas se conservan para poder estudiarlas en el chat de cuarentena.
    keep.update(t for t in tags if is_vetoed(t))
    promoted = _promoted().get(agent_id)
    if promoted:
        keep.add(promoted)
    return sorted(keep), [t for t in tags if t not in keep]


async def run(dry_run: bool) -> None:
    os.environ["PARADAX_TEACHER_MODE"] = "1"  # el modelo pedido manda sobre models.json
    from .quarantine import is_vetoed, ollama_env
    night = datetime.now().strftime("%Y%m%d")
    cases = await build_cases(night)
    if not cases:
        print("sin casos de evaluación esta noche")
        return
    history = _history()
    report = [f"# Scoreboard del generalista · {datetime.now():%Y-%m-%d %H:%M}",
              f"{len(cases)} casos NUEVOS esta noche · maestro {TEACHER} · "
              f"regla: racha ≥ {READY_STREAK} casos (fallo ≤ {3 / READY_STREAK:.0%} con 95 % de confianza)", ""]
    TEACHER_RAW_DIR.mkdir(parents=True, exist_ok=True)
    for agent_id in AGENTS:
        tags = _version_tags(agent_id)
        if not tags:
            continue
        traw_path = TEACHER_RAW_DIR / f"{night}-{agent_id}.json"
        teacher = _row(history, agent_id, TEACHER, night)
        if teacher is None or not traw_path.exists():
            teacher = await evaluate(agent_id, TEACHER, cases)
            teacher.update(ts=time.time(), night=night)
            traw_path.write_text(json.dumps([r.get("raw") for r in teacher.pop("_raws")],
                                            ensure_ascii=False), encoding="utf-8")
            history = [h for h in history if not (h["agent"] == agent_id and h["model"] == TEACHER
                                                  and h.get("night") == night)]
            history.append(teacher)
        traw = json.loads(traw_path.read_text(encoding="utf-8"))
        rows = []
        for tag in tags:
            row = _row(history, agent_id, tag, night)
            if row is None and is_vetoed(tag):
                # Sin examen: solo una fila de estado, fuera del histórico.
                row = {"agent": agent_id, "model": tag, "cases": 0, "metrics": {}, "score": 0.0,
                       "latency_s": None, "night": night, "skipped": "vetada"}
            elif row is None:  # cada versión conservada se examina cada noche con casos nuevos
                row = await evaluate(agent_id, tag, cases)
                row.update(ts=time.time(), night=night)
                apply_quarantine(row, scan(agent_id, tag, row.pop("_raws"), traw, cases))
                history.append(row)
            rows.append(row)
        SCOREBOARD.write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")

        t_stats = readiness(history, agent_id, TEACHER)
        stats = {r["model"]: readiness(history, agent_id, r["model"]) for r in rows}
        for r in rows:
            r["streak"] = stats[r["model"]]["streak"]
        keep, drop = retention(agent_id, rows, tags)

        report.append(f"## {agent_id}")
        report.append("| modelo | score hoy | racha | casos | P(acierto) | fallo máx. 95 % | estado |")
        report.append("|---|---|---|---|---|---|---|")
        report.append(f"| {TEACHER} | {teacher['score']:.2f} | {t_stats['streak']} | {t_stats['cases']} | "
                      f"{t_stats['laplace']:.0%} | — | maestro (fallo real {t_stats['fail_rate'] or 0:.0%}) |")
        for r in rows:
            st = stats[r["model"]]
            q = len(r.get("quarantine") or [])
            beats_teacher = (st["fail_rate"] or 0) <= (t_stats["fail_rate"] or 0)
            if r.get("skipped"):
                state = "⛔ vetada · no se examina hasta que la liberes"
            elif is_vetoed(r["model"]):
                state = f"⛔ en cuarentena ({q} casos)"
            elif r["model"] in drop:
                state = "se borra"
            elif st["streak"] >= READY_STREAK and beats_teacher and not fast_enough(r, teacher):
                state = (f"acierta como el maestro pero es más lenta "
                         f"({r['latency_s']}s frente a {teacher['latency_s']}s): no se promociona")
            elif st["streak"] >= READY_STREAK and beats_teacher:
                state = "✅ LISTA para promoción"
                flag = ROOT / "runs" / "nightly" / f"LISTO-{agent_id}.txt"
                if not flag.exists():
                    flag.write_text(f"{r['model']} cumple la regla: {json.dumps(st)}\n", encoding="utf-8")
                    _notify("Paradax", f"{r['model']} lista para promoción (racha {st['streak']})")
            else:
                state = f"acumulando ({st['streak']}/{READY_STREAK})"
            if q and not is_vetoed(r["model"]):
                state += f" · {q} reacciones raras"
            score = "—" if r.get("skipped") else f"{r['score']:.2f}"
            report.append(f"| {r['model']} | {score} | {st['streak']} | {st['cases']} | "
                          f"{st['laplace']:.0%} | {st['fail_upper_95']:.0%} | {state} |")
        report.append("")
        if not dry_run:
            for tag in drop:
                subprocess.run(["ollama", "rm", tag], capture_output=True, env=ollama_env())

    text = "\n".join(report)
    out = ROOT / "runs" / "nightly" / f"scoreboard-{night}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    print(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evalúa y poda las versiones del generalista")
    parser.add_argument("--dry-run", action="store_true", help="evalúa pero no borra nada")
    asyncio.run(run(parser.parse_args().dry_run))


if __name__ == "__main__":
    main()
