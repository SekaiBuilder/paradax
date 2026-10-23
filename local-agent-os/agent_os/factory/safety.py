from __future__ import annotations

"""Red de seguridad git: snapshot antes/después de cada run de agentes para que
TODO cambio sea reversible (deshacer).

El proyecto Paradax no era un repo, así que las ediciones de los agentes (vía
Claude Code o code tools) eran irreversibles. Esto crea/usa un repo en
PARADAX_ROOT con un .gitignore que excluye lo pesado, y permite volver atrás.
"""

import subprocess
from pathlib import Path
from typing import Any

from ..config import PARADAX_ROOT

GITIGNORE = """# Paradax safety-net (auto-generado) — excluye lo pesado/generado
.venv/
**/.venv/
__pycache__/
**/__pycache__/
*.pyc
node_modules/
**/node_modules/
.pytest_cache/
.DS_Store
# generados / modelos / medios
local-agent-os/runs/
local-agent-os/data/agent_os.sqlite3
local-agent-os/data/datasets/
local-agent-os/data/snapshots/
local-agent-os/training/fused/
local-agent-os/training/adapters/
local-agent-os/training/dataset/
media-manager/gifs/
media-manager/output/
media-manager/voiceovers/
media-manager/recorder/
media-manager/logs/
*.gif
*.mp4
*.mp3
*.png
*.jpg
*.jpeg
*.sqlite3
*.gguf
*.safetensors
"""


def _git(root: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(root), text=True, capture_output=True, timeout=60, check=check
    )


def available() -> bool:
    try:
        return _git(Path.cwd(), "--version").returncode == 0
    except Exception:
        return False


def is_repo(root: Path | None = None) -> bool:
    root = Path(root or PARADAX_ROOT)
    return _git(root, "rev-parse", "--is-inside-work-tree").returncode == 0


def ensure_repo(root: Path | None = None) -> bool:
    """Crea el repo de seguridad si no existe (con .gitignore e identidad local)."""
    root = Path(root or PARADAX_ROOT)
    if is_repo(root):
        return True
    gi = root / ".gitignore"
    if not gi.exists():
        gi.write_text(GITIGNORE, encoding="utf-8")
    if _git(root, "init").returncode != 0:
        return False
    # Identidad local para que los commits no fallen (no toca la global).
    _git(root, "config", "user.name", "Paradax Safety")
    _git(root, "config", "user.email", "safety@paradax.local")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "paradax: baseline (red de seguridad)", "--quiet")
    return True


def current_sha(root: Path | None = None) -> str:
    root = Path(root or PARADAX_ROOT)
    r = _git(root, "rev-parse", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else ""


def snapshot(message: str, root: Path | None = None) -> str:
    """Commitea el estado actual y devuelve el sha (punto de restauración)."""
    root = Path(root or PARADAX_ROOT)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message[:200], "--quiet", "--allow-empty")
    return current_sha(root)


def changed_files(since_sha: str, root: Path | None = None) -> list[str]:
    root = Path(root or PARADAX_ROOT)
    if not since_sha:
        return []
    r = _git(root, "diff", "--name-only", f"{since_sha}..HEAD")
    return [line for line in r.stdout.splitlines() if line.strip()]


def undo_to(sha: str, root: Path | None = None) -> dict[str, Any]:
    """Revierte el árbol de trabajo a un sha (deshacer un run de agentes)."""
    root = Path(root or PARADAX_ROOT)
    if not sha:
        return {"ok": False, "error": "sha vacío"}
    r = _git(root, "reset", "--hard", sha)
    return {"ok": r.returncode == 0, "sha": sha, "error": r.stderr.strip()[:200] if r.returncode else ""}
