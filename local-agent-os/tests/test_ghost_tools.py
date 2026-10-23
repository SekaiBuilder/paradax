from __future__ import annotations

import json

import pytest

from agent_os.factory.ghost import Ghost, GhostError
from agent_os.factory.skill_master import SkillMaster
from agent_os.factory import tool_catalog

TOOL_JSON = {
    "id": "scrape-prices",
    "name": "scrape_prices",
    "kind": "tool",
    "description": "Extrae precios visibles de una URL.",
    "signature": "scrape_prices(url: str) -> list[float]",
    "implementation": "def scrape_prices(url):\n    # TODO: implementar\n    return []",
}


def _ghost(tmp_path, out):
    async def fake_claude(prompt: str) -> str:
        return out
    return Ghost(call_claude=fake_claude, staging=tmp_path / "staging")


@pytest.mark.asyncio
async def test_tool_proposal_captures_code(tmp_path):
    ghost = _ghost(tmp_path, json.dumps(TOOL_JSON))
    p = await ghost.escalate("necesito scrapear precios", "no compila: falta tool")
    assert p.needs_human_code is True
    assert p.tool_name == "scrape_prices"
    assert "def scrape_prices" in p.tool_code
    assert p.tool_signature.startswith("scrape_prices")
    assert ghost.pending_tools() and ghost.pending_tools()[0].id == p.id


@pytest.mark.asyncio
async def test_approve_tool_writes_code_and_registers(tmp_path):
    ghost = _ghost(tmp_path, json.dumps(TOOL_JSON))
    p = await ghost.escalate("scrape", "falla")
    res = ghost.approve_tool(p.id, tools_dir=tmp_path / "gen")
    assert res["executed"] is False           # nunca ejecuta
    assert res["registered"] is True
    code_file = tmp_path / "gen" / "scrape_prices.py"
    assert code_file.exists()
    text = code_file.read_text()
    assert "NO se importa ni se ejecuta" in text   # cabecera de seguridad
    assert "def scrape_prices" in text
    assert tool_catalog.has_tool("scrape_prices")  # metadata sube el techo
    assert ghost.get(p.id).status == "approved"


@pytest.mark.asyncio
async def test_approve_tool_rejects_skill(tmp_path):
    skill = {"id": "x", "name": "X", "kind": "capability", "description": "d", "prompt": "haz X."}
    ghost = _ghost(tmp_path, json.dumps(skill))
    p = await ghost.escalate("algo", "falla")
    with pytest.raises(GhostError):
        ghost.approve_tool(p.id, tools_dir=tmp_path / "gen")


@pytest.mark.asyncio
async def test_skill_approve_rejects_tool(tmp_path):
    ghost = _ghost(tmp_path, json.dumps(TOOL_JSON))
    sm = SkillMaster(root=tmp_path / "skills")
    p = await ghost.escalate("scrape", "falla")
    with pytest.raises(GhostError):
        ghost.approve(p.id, sm)  # una tool no entra como skill de datos
