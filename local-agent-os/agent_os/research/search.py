from __future__ import annotations

"""Buscadores del Investigador.

  segura  SearXNG local (tu Mac, sin rastreo). Es el modo por defecto.
  libre   SearXNG y, si no está disponible o no encuentra nada, DuckDuckGo
          (más resultados, pero sale a un servicio externo).

SearXNG vive en localhost: es la ÚNICA dirección local que el Investigador
consulta, y solo su API de búsqueda (/search?format=json), nunca páginas.
"""

import os
import re
from html import unescape
from urllib.parse import parse_qs, unquote, urlsplit

import httpx

SEARXNG_URL = os.getenv("PARADAX_SEARXNG_URL", "http://127.0.0.1:8888").rstrip("/")
MODES = ("segura", "libre")


class SearchError(RuntimeError):
    pass


def searxng(query: str, limit: int = 5) -> list[dict]:
    try:
        resp = httpx.get(f"{SEARXNG_URL}/search", params={"q": query, "format": "json"}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise SearchError(f"SearXNG no disponible en {SEARXNG_URL}: {type(exc).__name__}") from exc
    return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", ""), "engine": "searxng"}
            for r in data.get("results", [])[:limit] if r.get("url", "").startswith(("http://", "https://"))]


_DDG_RESULT = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>', re.S)
_TAGS = re.compile(r"<[^>]+>")


def _ddg_target(href: str) -> str:
    href = unescape(href)
    if "duckduckgo.com/l/" in href:
        q = parse_qs(urlsplit(href if href.startswith("http") else "https:" + href).query)
        return unquote(q.get("uddg", [""])[0])
    return href


def duckduckgo(query: str, limit: int = 5) -> list[dict]:
    try:
        resp = httpx.post("https://html.duckduckgo.com/html/", data={"q": query}, timeout=12,
                          headers={"User-Agent": "Mozilla/5.0 (Macintosh) ParadaxResearcher/1.0"})
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        raise SearchError(f"DuckDuckGo no respondió: {type(exc).__name__}") from exc
    out = []
    for href, title, snippet in _DDG_RESULT.findall(resp.text):
        url = _ddg_target(href)
        if url.startswith(("http://", "https://")):
            out.append({"title": unescape(_TAGS.sub("", title)).strip(), "url": url,
                        "snippet": unescape(_TAGS.sub("", snippet)).strip(), "engine": "duckduckgo"})
        if len(out) >= limit:
            break
    return out


def search(query: str, mode: str = "segura", limit: int = 5) -> tuple[list[dict], list[str]]:
    """Devuelve (resultados, notas). Nunca lanza: las caídas van a notas."""
    if mode not in MODES:
        raise ValueError(f"modo: {' | '.join(MODES)}")
    notes: list[str] = []
    try:
        results = searxng(query, limit)
        if results or mode == "segura":
            return results, notes
        notes.append("SearXNG no encontró nada; se prueba DuckDuckGo (modo libre)")
    except SearchError as exc:
        notes.append(str(exc))
        if mode == "segura":
            notes.append("modo segura: no se usa ningún buscador externo")
            return [], notes
    try:
        return duckduckgo(query, limit), notes
    except SearchError as exc:
        notes.append(str(exc))
        return [], notes
