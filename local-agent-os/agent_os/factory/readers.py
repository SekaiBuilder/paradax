from __future__ import annotations

"""Los dos colaboradores del Entrenador: leen material para entrenar.

El usuario NO entrena agentes; el único que entrena es el Entrenador. Para
nutrirse de material, el Entrenador tiene dos colaboradores:

- `DocReaderAgent`  — lee PDFs y archivos de texto → texto plano.
- `UrlReaderAgent`  — lee una página web → texto plano.

Ambos son **durmientes** (`on_demand`): solo se activan cuando se les necesita.
Y **no son contactables** (`contactable=False`): se ven en el grafo de
interacciones, pero el usuario no puede hablar con ellos. El Entrenador los
invoca; nadie más.
"""

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..core.agent import Agent
from ..core.contract import AgentContract


class Material(BaseModel):
    """Material de entrenamiento extraído por un colaborador lector."""

    source: str
    kind: str            # pdf | text | url
    text: str
    chars: int


# ── extractores deterministas ──────────────────────────────────────────────
def extract_pdf(path: str | Path, max_chars: int = 100_000) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts = [(page.extract_text() or "") for page in reader.pages]
    return "\n".join(parts)[:max_chars].strip()


def extract_text_file(path: str | Path, max_chars: int = 100_000) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")[:max_chars].strip()


def fetch_url_text(url: str, max_chars: int = 100_000) -> str:
    import httpx

    resp = httpx.get(url, timeout=20, follow_redirects=True)
    resp.raise_for_status()
    html = resp.text
    # limpieza mínima: fuera scripts/estilos y etiquetas → texto legible
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


# ── colaboradores ────────────────────────────────────────────────────────────
class DocReaderAgent(Agent):
    """Colaborador durmiente del Entrenador: lee PDFs y archivos de texto."""

    contract = AgentContract(
        id="doc_reader",
        name="Lector de documentos",
        description="Lee PDFs y archivos de texto y extrae su contenido para el Entrenador",
        reads=("source",),
        writes="material",
        output_model=Material,
        allowed_tools=("read_pdf", "read_text"),
        uses_llm=False,
        contactable=False,
        on_demand=True,
    )

    async def execute(self, ctx: dict[str, Any]) -> Material:
        source = str(ctx["source"])
        if source.lower().endswith(".pdf"):
            text, kind = extract_pdf(source), "pdf"
        else:
            text, kind = extract_text_file(source), "text"
        return Material(source=source, kind=kind, text=text, chars=len(text))


class UrlReaderAgent(Agent):
    """Colaborador durmiente del Entrenador: lee una página web."""

    contract = AgentContract(
        id="url_reader",
        name="Lector de URLs",
        description="Lee una página web y extrae su texto para el Entrenador",
        reads=("url",),
        writes="material",
        output_model=Material,
        allowed_tools=("http_get",),
        uses_llm=False,
        contactable=False,
        on_demand=True,
    )

    async def execute(self, ctx: dict[str, Any]) -> Material:
        url = str(ctx["url"])
        text = fetch_url_text(url)
        return Material(source=url, kind="url", text=text, chars=len(text))
