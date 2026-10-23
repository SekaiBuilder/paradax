from __future__ import annotations

import re
from typing import Any

import httpx

from ..core.agent import Agent
from ..core.contract import AgentContract
from ..core.schemas import SelectorInventory

MAX_PER_KIND = 120


class PageInspectorAgent(Agent):
    """Descarga el HTML real de la URL y extrae los selectores que existen.

    No usa LLM: es una herramienta determinista. Su salida acota lo que el
    Action Planner puede usar — un selector que no está aquí ni en la
    whitelist conocida se rechaza.
    """

    contract = AgentContract(
        id="page_inspector",
        name="Page Inspector",
        description="Extrae ids, clases y data-attrs reales de la página objetivo",
        reads=("url",),
        writes="inventory",
        output_model=SelectorInventory,
        allowed_tools=("http_get",),
    )

    async def execute(self, ctx: dict[str, Any]) -> SelectorInventory:
        url = ctx["url"]
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "agent-os-inspector/1.0"})
                resp.raise_for_status()
                html = resp.text
        except Exception as exc:
            return SelectorInventory(
                url=url,
                fetched=False,
                note=f"No se pudo descargar la página: {type(exc).__name__}: {exc}"[:300],
            )

        ids = _dedup(re.findall(r'\bid="([a-zA-Z][\w-]*)"', html))[:MAX_PER_KIND]
        classes = _dedup(
            cls
            for chunk in re.findall(r'\bclass="([^"]+)"', html)
            for cls in chunk.split()
            if re.fullmatch(r"[a-zA-Z][\w-]*", cls)
        )[:MAX_PER_KIND]
        data_selectors = _dedup(
            f"[{name}='{value}']"
            for name, value in re.findall(r'\b(data-[\w-]+)="([^"]{1,40})"', html)
        )[:MAX_PER_KIND]

        note = ""
        if len(html) > 400_000:
            note = "HTML grande: inventario posiblemente parcial."
        return SelectorInventory(
            url=url, fetched=True, ids=ids, classes=classes, data_selectors=data_selectors, note=note
        )


def _dedup(items) -> list[str]:
    seen: dict[str, None] = {}
    for it in items:
        seen.setdefault(it)
    return list(seen)
