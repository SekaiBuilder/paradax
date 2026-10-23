from __future__ import annotations

"""Investigador: encargos de búsqueda acotados y su registro."""

import asyncio
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...research import researcher

router = APIRouter(prefix="/api/research")


class ResearchRequest(BaseModel):
    question: str
    mode: str = "segura"


@router.post("")
async def research(req: ResearchRequest):
    try:
        return await asyncio.to_thread(researcher.investigate, req.question, "operador", req.mode)
    except researcher.ResearchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/log")
def research_log(limit: int = 50):
    path = researcher.RESEARCH_DIR / "log.jsonl"
    if not path.exists():
        return {"entries": []}
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    return {"entries": [json.loads(line) for line in reversed(lines) if line.strip()]}
