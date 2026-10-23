from __future__ import annotations

"""Tools seguras para que agentes construidos trabajen sobre codigo local.

Todas las rutas quedan encerradas en PARADAX_ROOT. No hay shell libre: los tests
se ejecutan solo por pytest y las ediciones son escritura/reemplazo explicito.
"""

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..config import PARADAX_ROOT

_EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    "training/fused",
    "training/adapters",
}


def _root() -> Path:
    return PARADAX_ROOT.resolve()


def _is_excluded(path: Path) -> bool:
    rel = path.relative_to(_root())
    parts = rel.parts
    joined = "/".join(parts)
    return any(part in _EXCLUDED_DIRS for part in parts) or any(
        joined.startswith(item + "/") for item in _EXCLUDED_DIRS
    )


def _resolve(path: str | os.PathLike[str]) -> Path:
    raw = Path(path)
    target = raw if raw.is_absolute() else _root() / raw
    resolved = target.resolve()
    root = _root()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"ruta fuera de PARADAX_ROOT: {path}")
    return resolved


def _rel(path: Path) -> str:
    return str(path.relative_to(_root()))


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        n = int(value)
    except Exception:
        n = default
    return max(low, min(high, n))


def _path_alias(path: str | None = None, **aliases: Any) -> str:
    value = path or aliases.get("file") or aliases.get("filepath") or aliases.get("target")
    if not value:
        raise ValueError("falta path")
    return str(value)


def _scope_pattern(pattern: str, path: str | None = None, directory: str | None = None) -> str:
    scope = path or directory
    if not scope:
        return pattern or "**/*"
    root = _root()
    raw = Path(str(scope))
    rel = _resolve(raw).relative_to(root) if raw.is_absolute() else raw
    text = str(rel).strip("/")
    if not text:
        return pattern or "**/*"
    if any(ch in text for ch in "*?[]"):
        return text
    if Path(text).suffix:
        return text
    return f"{text}/**/*"


def code_list_files(
    pattern: str = "**/*",
    max_results: int = 200,
    path: str | None = None,
    directory: str | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    """Lista archivos dentro de PARADAX_ROOT, excluyendo dependencias pesadas."""
    limit = _clamp_int(max_results, 200, 1, 1000)
    pattern = _scope_pattern(pattern, path=path, directory=directory)
    files: list[str] = []
    root = _root()
    for path in sorted(root.rglob(pattern or "*")):
        if len(files) >= limit:
            break
        if not path.is_file():
            continue
        try:
            if _is_excluded(path):
                continue
        except ValueError:
            continue
        files.append(_rel(path))
    return {"root": str(root), "files": files, "truncated": len(files) >= limit}


def code_read_file(path: str | None = None, max_chars: int = 20_000, **aliases: Any) -> dict[str, Any]:
    """Lee un archivo UTF-8 dentro de PARADAX_ROOT."""
    path = _path_alias(path, **aliases)
    target = _resolve(path)
    if not target.is_file():
        raise FileNotFoundError(path)
    limit = _clamp_int(max_chars, 20_000, 1, 100_000)
    text = target.read_text(encoding="utf-8")
    return {"path": _rel(target), "content": text[:limit], "truncated": len(text) > limit}


def code_search(
    query: str = "",
    glob: str = "*",
    max_results: int = 80,
    path: str | None = None,
    directory: str | None = None,
    pattern: str | None = None,
    text: str | None = None,
    term: str | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    """Busca texto con rg si esta disponible; devuelve coincidencias compactas."""
    query = query or text or term or ""
    if not query:
        raise ValueError("query vacio")
    if pattern and glob == "*":
        glob = pattern
    glob = _scope_pattern(glob, path=path, directory=directory)
    limit = _clamp_int(max_results, 80, 1, 300)
    root = _root()
    cmd = [
        "rg",
        "--line-number",
        "--no-heading",
        "--color",
        "never",
        "--glob",
        glob or "*",
        "--glob",
        "!node_modules/**",
        "--glob",
        "!**/node_modules/**",
        "--glob",
        "!.venv/**",
        "--glob",
        "!**/.venv/**",
        "--glob",
        "!training/fused/**",
        "--glob",
        "!**/training/fused/**",
        "--glob",
        "!training/adapters/**",
        "--glob",
        "!**/training/adapters/**",
        query,
        str(root),
    ]
    try:
        proc = subprocess.run(cmd, cwd=root, text=True, capture_output=True, timeout=20)
        lines = proc.stdout.splitlines()
    except FileNotFoundError:
        lines = _search_without_rg(query, glob or "*")

    results = []
    for line in lines[:limit]:
        if line.startswith(str(root)):
            line = line.replace(str(root) + os.sep, "", 1)
        results.append(line[:600])
    return {"query": query, "results": results, "truncated": len(lines) > limit}


def _search_without_rg(query: str, pattern: str) -> list[str]:
    root = _root()
    out: list[str] = []
    for path in sorted(root.rglob(pattern)):
        if not path.is_file():
            continue
        try:
            if _is_excluded(path):
                continue
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if query in line:
                out.append(f"{_rel(path)}:{lineno}:{line}")
    return out


def code_replace(
    path: str | None = None,
    old: str = "",
    new: str = "",
    count: int = 1,
    **aliases: Any,
) -> dict[str, Any]:
    """Reemplaza texto exacto en un archivo; falla si el texto no existe."""
    path = _path_alias(path, **aliases)
    if not old:
        raise ValueError("old no puede estar vacio")
    target = _resolve(path)
    if not target.is_file():
        raise FileNotFoundError(path)
    text = target.read_text(encoding="utf-8")
    requested = _clamp_int(count, 1, 1, 100)
    found = text.count(old)
    if found == 0:
        raise ValueError("texto old no encontrado")
    replacements = min(found, requested)
    updated = text.replace(old, new, replacements)
    target.write_text(updated, encoding="utf-8")
    return {"path": _rel(target), "replacements": replacements}


def code_write_file(
    path: str | None = None,
    content: str = "",
    create: bool = False,
    max_chars: int = 200_000,
    **aliases: Any,
) -> dict[str, Any]:
    """Escribe contenido completo en un archivo dentro de PARADAX_ROOT."""
    path = _path_alias(path, **aliases)
    target = _resolve(path)
    if target.exists() and not target.is_file():
        raise IsADirectoryError(path)
    if not target.exists() and not create:
        raise FileNotFoundError(f"{path} no existe; usa create=true para crearlo")
    limit = _clamp_int(max_chars, 200_000, 1, 500_000)
    if len(content) > limit:
        raise ValueError(f"content demasiado grande ({len(content)} > {limit})")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"path": _rel(target), "bytes": len(content.encode("utf-8"))}


def code_run_pytest(args: str = "", cwd: str = "local-agent-os", timeout_s: int = 120) -> dict[str, Any]:
    """Ejecuta pytest sin shell libre. `cwd` debe quedar dentro de PARADAX_ROOT."""
    workdir = _resolve(cwd)
    if not workdir.is_dir():
        raise NotADirectoryError(cwd)
    timeout = _clamp_int(timeout_s, 120, 1, 300)
    py = workdir / ".venv" / "bin" / "python"
    python = str(py) if py.exists() else sys.executable
    extra = shlex.split(args or "")
    cmd = [python, "-m", "pytest", *extra]
    proc = subprocess.run(cmd, cwd=workdir, text=True, capture_output=True, timeout=timeout)
    return {
        "cwd": _rel(workdir),
        "command": " ".join(shlex.quote(part) for part in cmd),
        "exit_code": proc.returncode,
        "stdout": proc.stdout[-6000:],
        "stderr": proc.stderr[-3000:],
    }
