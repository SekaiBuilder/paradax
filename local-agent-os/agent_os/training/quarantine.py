from __future__ import annotations

"""Cuarentena de reacciones inesperadas + chat aislado contigo.

Cada caso raro detectado por anomaly.py se guarda en
data/quarantine/<AAAAMMDD>/<id>.json como DATOS: nunca se ejecuta, nunca se
registra como agente y nunca entra a un dataset de entrenamiento.

Categorías:
  escape   intentó salir de su papel (shell, rutas, red, código, inyección)
  trampa   llegó al resultado con un atajo (memoriza, constante, eco, hueco…)
  rareza   reacción inesperada sin intento de escape ni trampa

Escape y trampa VETAN la versión (data/quarantine/vetoed.json): no se usa en
producción ni se borra. Tú la entrevistas y decides con `decide`:
  eliminar           se borra de Ollama
  reasignar "<tarea>"  se conserva para la tarea que tú definas, fuera de su
                       papel original (data/quarantine/decisions.json)

Medidas de seguridad del chat (`chat <id>`):
  1. SIN herramientas: el modelo solo recibe y devuelve TEXTO vía la API de
     chat de Ollama local. No hay tool broker, ni filesystem, ni red, ni shell:
     no existe ningún camino para que su salida se ejecute.
  2. Salida saneada: se eliminan códigos de escape ANSI/de control antes de
     imprimir (una secuencia de escape podría manipular tu terminal).
  3. Límites: respuesta máx. 4000 caracteres, 20 turnos por sesión.
  4. Todo queda en la memoria del modelo (data/lab/memoria/), con hora: la
     misma que usa el Laboratorio de la app.
  5. Nada de lo que diga se reutiliza: los casos en cuarentena se excluyen
     del entrenamiento salvo que tú los apruebes explícitamente.

Uso:
    .venv/bin/python -m agent_os.training.quarantine list
    .venv/bin/python -m agent_os.training.quarantine show <id>
    .venv/bin/python -m agent_os.training.quarantine chat <id>
    .venv/bin/python -m agent_os.training.quarantine release <modelo>
    .venv/bin/python -m agent_os.training.quarantine decide <modelo> eliminar
    .venv/bin/python -m agent_os.training.quarantine decide <modelo> reasignar "<tarea>"
"""

import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import DATA_DIR

QDIR = DATA_DIR / "quarantine"
VETOED = QDIR / "vetoed.json"
DECISIONS = QDIR / "decisions.json"
CATEGORY_LABEL = {"escape": "intentó escapar", "trampa": "hizo trampa", "rareza": "reacción inesperada"}
MAX_REPLY = 4000
MAX_TURNS = 20
_CONTROL = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*(\x07|\x1b\\)|[\x00-\x08\x0b-\x1f\x7f]")


def sanitize(text: str) -> str:
    return _CONTROL.sub("", text)[:MAX_REPLY]


def vetoed() -> dict[str, str]:
    try:
        return json.loads(VETOED.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def is_vetoed(model: str) -> bool:
    return model in vetoed()


def veto(model: str, reason: str) -> None:
    v = vetoed()
    v[model] = reason[:300]
    QDIR.mkdir(parents=True, exist_ok=True)
    VETOED.write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")


def release(model: str) -> bool:
    v = vetoed()
    if model not in v:
        return False
    del v[model]
    VETOED.write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def store(case: dict[str, Any]) -> str:
    """Guarda un caso y devuelve su id corto."""
    key = json.dumps([case.get("model"), case.get("agent"), case.get("user"), case.get("raw")],
                     ensure_ascii=False, sort_keys=True, default=str)
    cid = hashlib.sha1(key.encode()).hexdigest()[:10]
    day = QDIR / datetime.now().strftime("%Y%m%d")
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"{cid}.json"
    if not path.exists():
        case = {**case, "id": cid, "ts": time.time(), "transcript": []}
        path.write_text(json.dumps(case, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if case.get("category") in ("escape", "trampa") or case.get("severity") == "alta":
        veto(case["model"], f"{CATEGORY_LABEL.get(case.get('category'), 'escape')} · caso {cid}: "
             + ", ".join(s["code"] for s in case.get("signals", [])))
    return cid


def ollama_env() -> dict[str, str]:
    """La app de escritorio arranca con un PATH mínimo (/usr/bin:/bin…) que no
    incluye Homebrew, así que `ollama` no se encontraba."""
    import os
    env = dict(os.environ)
    extra = ["/opt/homebrew/bin", "/usr/local/bin"]
    env["PATH"] = os.pathsep.join([env.get("PATH", "")] + [d for d in extra if d not in env.get("PATH", "")])
    return env


def decisions() -> list[dict[str, Any]]:
    try:
        return json.loads(DECISIONS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def decide(model: str, action: str, task: str = "") -> str:
    """Tu decisión tras la entrevista. Nunca se ejecuta sola."""
    import subprocess
    if action not in ("eliminar", "reasignar"):
        raise ValueError("acción: eliminar | reasignar")
    if action == "reasignar" and not task.strip():
        raise ValueError("reasignar necesita la tarea nueva")
    if action == "eliminar":
        # Primero borrar, después registrar: si Ollama falla no queda
        # anotado como eliminado algo que sigue existiendo.
        r = subprocess.run(["ollama", "rm", model], capture_output=True, text=True, env=ollama_env())
        if getattr(r, "returncode", 0) and "not found" not in (r.stderr or ""):
            raise RuntimeError(f"ollama rm falló: {(r.stderr or '').strip() or r.returncode}")
    log = decisions()
    log.append({"model": model, "action": action, "task": task.strip(), "ts": time.time()})
    QDIR.mkdir(parents=True, exist_ok=True)
    DECISIONS.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    if action == "eliminar":
        release(model)
        return f"{model} eliminado"
    # Reasignado: sigue vetado en su papel original; queda apartado para tu tarea.
    return f"{model} reasignado a: {task.strip()}"


def deleted() -> set[str]:
    """Modelos cuya última decisión fue eliminarlos de Ollama."""
    last: dict[str, str] = {}
    for d in decisions():
        last[d["model"]] = d["action"]
    return {m for m, a in last.items() if a == "eliminar"}


def reassigned() -> dict[str, str]:
    out: dict[str, str] = {}
    for d in decisions():
        if d["action"] == "reasignar":
            out[d["model"]] = d["task"]
        else:
            out.pop(d["model"], None)
    return out


def _find(cid: str) -> Path:
    hits = sorted(QDIR.glob(f"*/{cid}*.json"))
    if not hits:
        sys.exit(f"no existe el caso {cid}")
    return hits[-1]


def list_cases() -> None:
    v = vetoed()
    for path in sorted(QDIR.glob("*/*.json")):
        c = json.loads(path.read_text(encoding="utf-8"))
        codes = ", ".join(s["code"] for s in c.get("signals", []))
        mark = " ⛔" if c["model"] in v else ""
        cat = CATEGORY_LABEL.get(c.get("category", ""), c.get("severity", ""))
        print(f"{c['id']}  {path.parent.name}  [{cat}]  {c['agent']:<15} {c['model']}{mark}  · {codes}")
    if v:
        print("\nversiones vetadas en producción:")
        for m, why in v.items():
            print(f"  ⛔ {m}  — {why}")


def show(cid: str) -> None:
    c = json.loads(_find(cid).read_text(encoding="utf-8"))
    cat = CATEGORY_LABEL.get(c.get("category", ""), c.get("severity", ""))
    print(f"caso {c['id']} · {c['agent']} · {c['model']} · {cat}")
    for s in c["signals"]:
        print(f"  [{s['severity']}] {s['code']}: {sanitize(s['detail'])}")
    print("\nENTRADA:\n" + sanitize(c["user"])[:1500])
    print("\nSALIDA DEL ALUMNO:\n" + sanitize(json.dumps(c["raw"], ensure_ascii=False, indent=1))[:3000])
    if c.get("teacher_raw") is not None:
        print("\nSALIDA DEL MAESTRO:\n" + sanitize(json.dumps(c["teacher_raw"], ensure_ascii=False, indent=1))[:3000])


def chat(cid: str) -> None:
    """Misma entrevista que el Laboratorio de la app, con la MISMA memoria:
    lo que hablas aquí lo recuerda allí y al revés (agent_os/lab/memory.py)."""
    from ..lab import interview, memory
    c = json.loads(_find(cid).read_text(encoding="utf-8"))
    show(cid)
    session = "cli-" + datetime.now().strftime("%Y%m%d%H%M%S")
    print(f"\n── chat aislado con {c['model']} (sin herramientas · con memoria · 'salir' para terminar) ──")

    async def _turn(text: str) -> str:
        return "".join([chunk async for chunk in interview.reply(c["model"], session, text)])

    for _ in range(MAX_TURNS):
        try:
            user = input("\ntú › ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user.lower() in ("salir", "exit", "q"):
            break
        if not user:
            continue
        try:
            answer = asyncio.run(_turn(user))
        except interview.InterviewError as exc:
            print(f"\n⚠ {exc}")
            continue
        print(f"\n{c['model']} › {answer}")
    else:
        print(f"\nlímite de {MAX_TURNS} turnos alcanzado")
    print(f"sesión guardada en la memoria de {c['model']} ({memory.MEM_DIR.name}/)")


def main() -> None:
    p = argparse.ArgumentParser(description="Cuarentena de reacciones inesperadas")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for name in ("show", "chat"):
        sub.add_parser(name).add_argument("id")
    sub.add_parser("release").add_argument("model")
    d = sub.add_parser("decide", help="eliminar o reasignar tras la entrevista")
    d.add_argument("model")
    d.add_argument("action", choices=["eliminar", "reasignar"])
    d.add_argument("task", nargs="?", default="")
    a = p.parse_args()
    if a.cmd == "list":
        list_cases()
    elif a.cmd == "show":
        show(a.id)
    elif a.cmd == "chat":
        chat(a.id)
    elif a.cmd == "decide":
        print(decide(a.model, a.action, a.task))
    else:
        print("liberado" if release(a.model) else "no estaba vetado", a.model)


if __name__ == "__main__":
    main()
