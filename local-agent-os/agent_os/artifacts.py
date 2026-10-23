from __future__ import annotations

"""Materializador de resultados: convierte el output de cada run en ARCHIVOS.

El problema que resuelve: los agentes producen contenido válido (reglas,
guías, configs) pero vivía solo como JSON dentro de SQLite — para el usuario
"la app no hacía nada". Ahora cada run de proyecto escribe su trabajo en

    ~/paradax/resultados/<proyecto>/<run>/
        README.md                  ← petición, agentes, índice
        <agente>/<campo>.md        ← textos y listas, legibles
        <agente>/<campo>.json      ← estructuras (reglas, datos)

Heurística de formato por campo del output:
  - str largo (>80 chars) o con saltos de línea → .md
  - lista de strings → .md numerado (pasos, checklists)
  - dict / lista de dicts → .json indentado
  - escalares cortos → van al resumen del agente en su _resumen.md
"""

import json
import re
import time
from pathlib import Path
from typing import Any

from .config import RESULTS_DIR


def _slug(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-zA-Z0-9áéíóúñü_-]+", "-", str(text).strip().lower()).strip("-")
    return s[:max_len] or "x"


def _write_field(agent_dir: Path, key: str, value: Any) -> str | None:
    """Escribe un campo del output como archivo. Devuelve el nombre o None si
    el campo es corto y va mejor en el resumen."""
    name = _slug(key)
    if isinstance(value, str):
        if len(value) > 80 or "\n" in value:
            path = agent_dir / f"{name}.md"
            path.write_text(f"# {key}\n\n{value}\n", encoding="utf-8")
            return path.name
        return None  # corto → al resumen
    if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
        path = agent_dir / f"{name}.md"
        body = "\n".join(f"{i}. {v}" for i, v in enumerate(value, 1))
        path.write_text(f"# {key}\n\n{body}\n", encoding="utf-8")
        return path.name
    if isinstance(value, (dict, list)):
        path = agent_dir / f"{name}.json"
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path.name
    return None


def materialize_run(
    project_id: str,
    project_name: str,
    run_id: str,
    request: str,
    events: list[dict[str, Any]],
) -> Path | None:
    """Escribe los outputs de los agent_completed del run como archivos.
    Devuelve la carpeta creada, o None si no había nada que materializar."""
    import os
    if os.getenv("PYTEST_CURRENT_TEST"):
        return None  # los tests ejecutan runs reales: no ensucian ~/paradax/resultados

    completed = [e["payload"] for e in events if e.get("kind") == "agent_completed"]
    completed = [p for p in completed if p.get("output")]
    if not completed:
        return None

    short = run_id.rsplit("-", 1)[-1]
    stamp = time.strftime("%Y-%m-%d_%H%M")
    run_dir = RESULTS_DIR / _slug(project_id) / f"{stamp}_{short}"
    run_dir.mkdir(parents=True, exist_ok=True)

    index_lines: list[str] = []
    for p in completed:
        agent = p.get("agent", "agente")
        out = p.get("output", {})
        agent_dir = run_dir / _slug(agent)
        agent_dir.mkdir(exist_ok=True)

        shorts: list[str] = []
        files: list[str] = []
        for k, v in out.items():
            written = _write_field(agent_dir, k, v)
            if written:
                files.append(written)
            else:
                shorts.append(f"- **{k}**: {v}")

        resumen = agent_dir / "_resumen.md"
        resumen.write_text(
            f"# {agent}\n\n"
            + ("\n".join(shorts) + "\n\n" if shorts else "")
            + ("Archivos:\n" + "\n".join(f"- [{f}]({f})" for f in files) + "\n" if files else ""),
            encoding="utf-8",
        )
        index_lines.append(
            f"- **{agent}/** — " + (", ".join(files) if files else "ver _resumen.md")
        )

    (run_dir / "README.md").write_text(
        f"# {project_name}\n\n"
        f"**Petición:** {request}\n\n"
        f"**Run:** `{run_id}` · {time.strftime('%Y-%m-%d %H:%M')}\n\n"
        f"## Resultados por agente\n\n" + "\n".join(index_lines) + "\n",
        encoding="utf-8",
    )
    return run_dir


def list_results(project_id: str) -> list[dict[str, Any]]:
    """Runs materializados de un proyecto (más reciente primero) con sus archivos."""
    base = RESULTS_DIR / _slug(project_id)
    if not base.exists():
        return []
    items = []
    for d in sorted(base.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        files = sorted(
            str(f.relative_to(d)) for f in d.rglob("*") if f.is_file()
        )
        items.append({"name": d.name, "path": str(d), "files": files})
    return items
