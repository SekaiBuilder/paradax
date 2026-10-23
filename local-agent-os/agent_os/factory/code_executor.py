from __future__ import annotations

"""Ejecución real de cambios de código vía Claude Code (`claude -p`).

El paso "hacerlo realidad" del híbrido: cuando un agente ejecutor local
(implementador) no logra cambiar nada, se escala AQUÍ. Claude Code sí lee,
edita y prueba de verdad en el workspace.

Garantías de honestidad:
- Los archivos cambiados se calculan DETERMINISTAMENTE comparando hashes del
  árbol antes/después — no se confía en lo que el modelo dice que cambió.
- Todo ocurre dentro del workspace (cwd) y con un timeout acotado.
"""

import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Awaitable, Callable

# El modelo por defecto del CLI `claude` puede no estar disponible (p. ej. Fable 5
# caído). Forzamos uno disponible y capaz para editar código.
CLAUDE_MODEL = os.getenv("PARADAX_CLAUDE_MODEL", "sonnet")

_EXCLUDED = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache",
             "runs", "data", "gifs", "output", "voiceovers", "recorder", "fused", "adapters"}
_MAX_FILE = 1_000_000  # no hashear binarios/medios grandes

# Inyectable para tests: (prompt, cwd) -> texto de salida de claude.
ClaudeRunner = Callable[[str, Path], Awaitable[str]]


def _hash_tree(root: Path) -> dict[str, str]:
    """Hash de cada archivo de texto/código bajo root (rápido: salta pesados)."""
    out: dict[str, str] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in _EXCLUDED for part in rel.parts):
            continue
        try:
            if path.stat().st_size > _MAX_FILE:
                continue
            out[str(rel)] = hashlib.md5(path.read_bytes()).hexdigest()
        except OSError:
            continue
    return out


def _diff(before: dict[str, str], after: dict[str, str]) -> list[str]:
    changed = [p for p, h in after.items() if before.get(p) != h]
    changed += [p for p in before if p not in after]  # borrados
    return sorted(set(changed))


def _build_prompt(task: str, technical_spec: Any) -> str:
    spec = ""
    if technical_spec:
        spec = "\nEspecificación técnica:\n" + (
            json.dumps(technical_spec, ensure_ascii=False)[:2000]
            if not isinstance(technical_spec, str) else technical_spec[:2000]
        )
    return (
        "Eres el ejecutor de cambios del proyecto Paradax. El directorio actual ES el workspace.\n"
        f"Tarea concreta a realizar AHORA: {task}\n" + spec + "\n\n"
        "Haz el cambio mínimo y correcto editando los archivos REALES necesarios. "
        "Trabaja sobre la petición literal; no inventes otra tarea. Si tiene sentido, "
        "corre los tests. Cuando termines, responde en la última línea con un JSON: "
        '{"summary": "...", "changed_files": ["..."], "tests_run": ["..."], "status": "done|blocked"}.'
    )


async def claude_execute(
    task: str,
    cwd: Path,
    technical_spec: Any = None,
    timeout: int = 420,
    _claude: ClaudeRunner | None = None,
) -> dict[str, Any]:
    """Ejecuta la tarea con Claude Code y devuelve el reporte real."""
    cwd = Path(cwd)
    before = _hash_tree(cwd)
    runner = _claude or _real_claude
    raw = ""
    error = ""
    try:
        raw = await asyncio.wait_for(runner(_build_prompt(task, technical_spec), cwd), timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"[:300]
    after = _hash_tree(cwd)
    changed = _diff(before, after)

    status = "done" if changed else "blocked"
    summary = _extract_summary(raw) or (
        f"Claude Code modificó {len(changed)} archivo(s)." if changed
        else f"Claude Code no cambió archivos. {error}".strip()
    )
    return {
        "summary": summary,
        "changed_files": changed,
        "tests_run": [],
        "status": status,
        "executor": "claude_code",
        "error": error,
    }


def _extract_summary(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:  # envelope de --output-format json
        env = json.loads(raw)
        if isinstance(env, dict) and isinstance(env.get("result"), str):
            raw = env["result"]
    except json.JSONDecodeError:
        pass
    m = re.search(r'\{[^{}]*"summary"[^{}]*\}', raw, re.DOTALL)
    if m:
        try:
            return str(json.loads(m.group(0)).get("summary", ""))[:300]
        except json.JSONDecodeError:
            pass
    return raw.splitlines()[-1][:200] if raw else ""


async def _real_claude(prompt: str, cwd: Path) -> str:
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", prompt,
        "--output-format", "json",
        "--permission-mode", "bypassPermissions",
        "--model", CLAUDE_MODEL,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    text = out.decode(errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p falló (exit {proc.returncode}): {err.decode(errors='replace')[:300] or text[:300]}")
    # El CLI puede salir 0 pero con is_error (p. ej. modelo no disponible).
    try:
        env = json.loads(text)
        if isinstance(env, dict) and env.get("is_error"):
            raise RuntimeError(f"claude error: {str(env.get('result'))[:300]}")
    except json.JSONDecodeError:
        pass
    return text
