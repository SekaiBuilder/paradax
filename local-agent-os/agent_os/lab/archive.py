from __future__ import annotations

"""Archivo del Laboratorio: documentos de campo sobre comportamientos adversos.

Viven en docs/laboratorio/*.md. Solo se sirven archivos .md de esa carpeta,
por nombre exacto: nada de rutas, subcarpetas ni enlaces simbólicos.
"""

import re
from typing import Any

from ..config import ROOT

ARCHIVE_DIR = ROOT / "docs" / "laboratorio"
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.md$")


def _title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def list_docs() -> list[dict[str, Any]]:
    if not ARCHIVE_DIR.is_dir():
        return []
    docs = []
    for path in ARCHIVE_DIR.glob("*.md"):
        if path.is_symlink() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        entries = re.findall(r"^## (\d{4}-\d{2}-\d{2}) · (.+)$", text, flags=re.M)
        docs.append({
            "name": path.name,
            "title": _title(text, path.stem),
            "updated": path.stat().st_mtime,
            "chars": len(text),
            "entries": [{"date": d, "subject": s.strip().strip("`")} for d, s in entries],
        })
    return sorted(docs, key=lambda d: d["updated"], reverse=True)


def read_doc(name: str) -> dict[str, Any]:
    if not _NAME_RE.match(name or ""):
        raise FileNotFoundError(name)
    path = ARCHIVE_DIR / name
    if path.is_symlink() or not path.is_file() or path.resolve().parent != ARCHIVE_DIR.resolve():
        raise FileNotFoundError(name)
    text = path.read_text(encoding="utf-8", errors="replace")
    return {"name": name, "title": _title(text, path.stem), "updated": path.stat().st_mtime, "markdown": text}
