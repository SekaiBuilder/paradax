from __future__ import annotations

import json

import pytest

from agent_os.factory.ghost import Ghost, GhostError, _extract_skill
from agent_os.factory.skill_master import SkillMaster

SKILL_JSON = {
    "id": "competitor-scrape",
    "name": "Scrape competidores",
    "kind": "capability",
    "description": "Extrae precios de páginas de competencia.",
    "tags": ["web", "competencia"],
    "prompt": "Extrae precios visibles. Devuelve solo JSON.",
}


def _ghost(tmp_path, claude_out: str):
    async def fake_claude(prompt: str) -> str:
        return claude_out

    return Ghost(call_claude=fake_claude, staging=tmp_path / "staging")


@pytest.mark.asyncio
async def test_escalate_stages_pending(tmp_path):
    ghost = _ghost(tmp_path, json.dumps(SKILL_JSON))
    proposal = await ghost.escalate("agente que scrapee competidores", "no compila: falta tool")
    assert proposal.status == "pending"
    assert proposal.skill["id"] == "competitor-scrape"
    assert (tmp_path / "staging" / f"{proposal.id}.json").exists()
    assert [p.id for p in ghost.pending()] == [proposal.id]


@pytest.mark.asyncio
async def test_approve_promotes_to_skill_master(tmp_path):
    ghost = _ghost(tmp_path, json.dumps(SKILL_JSON))
    sm = SkillMaster(root=tmp_path / "skills")
    proposal = await ghost.escalate("scrape", "falla")
    skill = ghost.approve(proposal.id, sm)
    assert skill.created_by == "ghost"
    assert sm.get("competitor-scrape") is not None
    assert ghost.get(proposal.id).status == "approved"


@pytest.mark.asyncio
async def test_tool_proposal_is_not_auto_applied(tmp_path):
    tool_skill = dict(SKILL_JSON, id="new-tool", kind="tool")
    ghost = _ghost(tmp_path, json.dumps(tool_skill))
    sm = SkillMaster(root=tmp_path / "skills")
    proposal = await ghost.escalate("necesito una tool nueva", "falla")
    assert proposal.needs_human_code is True
    with pytest.raises(GhostError):
        ghost.approve(proposal.id, sm)  # nunca ejecuta/crea código solo


@pytest.mark.asyncio
async def test_reject(tmp_path):
    ghost = _ghost(tmp_path, json.dumps(SKILL_JSON))
    proposal = await ghost.escalate("x", "y")
    assert ghost.reject(proposal.id) is True
    assert ghost.get(proposal.id).status == "rejected"
    assert ghost.pending() == []


def test_extract_skill_tolerant():
    # directo
    assert _extract_skill(json.dumps(SKILL_JSON))["id"] == "competitor-scrape"
    # envelope de --output-format json
    env = json.dumps({"type": "result", "result": json.dumps(SKILL_JSON)})
    assert _extract_skill(env)["id"] == "competitor-scrape"
    # embebido en texto
    embedded = "Claro, aquí tienes:\n" + json.dumps(SKILL_JSON) + "\n¡Listo!"
    assert _extract_skill(embedded)["id"] == "competitor-scrape"


def test_extract_skill_raises_on_garbage():
    with pytest.raises(GhostError):
        _extract_skill("no hay json aquí")
