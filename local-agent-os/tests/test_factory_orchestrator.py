from __future__ import annotations

import json

import pytest

import agent_os.core.agent as core_agent
from agent_os.factory.factory import AgentFactory
from agent_os.factory.ghost import Ghost
from agent_os.factory.loader import DynamicRegistry
from agent_os.factory.skill_master import SkillMaster

GOOD_SPEC = {
    "id": "investigador",
    "name": "Investigador",
    "description": "Resume páginas.",
    "reads": ["url"],
    "writes": "research",
    "output_schema": {"resumen": "str"},
    "tools": ["http_get"], "uses_tools": True,
    "skills": [],
    "prompt": "Eres un investigador. Recibes la entrada del contexto, la analizas paso a paso según la tarea descrita, aplicas criterios claros y verificables y respondes con los campos del schema. Devuelve solo JSON con resumen.",
    "uses_llm": True,
    "max_retries": 1,
    "evals": [],
}
BAD_SPEC = dict(GOOD_SPEC, id="roto", output_schema={"mal nombre": "str"})


def _factory(tmp_path, spec_response, claude_out="{}"):
    async def fake_chat(model, system, user):
        return spec_response

    core_agent.chat_json = fake_chat  # parcheado a nivel módulo

    async def fake_claude(prompt):
        return claude_out

    return AgentFactory(
        skill_master=SkillMaster(root=tmp_path / "skills"),
        registry=DynamicRegistry(root=tmp_path / "specs"),
        ghost=Ghost(call_claude=fake_claude, staging=tmp_path / "staging"),
    )


@pytest.fixture(autouse=True)
def _restore_chat():
    original = core_agent.chat_json
    yield
    core_agent.chat_json = original


@pytest.mark.asyncio
async def test_build_success_registers_agent(tmp_path):
    fac = _factory(tmp_path, GOOD_SPEC)
    report = await fac.build("agente que investigue páginas")
    assert report.ok and report.registered
    assert report.spec["id"] == "investigador"
    assert fac.registry.get("investigador") is not None


@pytest.mark.asyncio
async def test_build_failure_without_escalation(tmp_path):
    fac = _factory(tmp_path, BAD_SPEC)
    report = await fac.build("algo imposible", escalate=False)
    assert report.ok is False
    assert report.proposal is None
    assert report.error


@pytest.mark.asyncio
async def test_build_failure_escalates_to_ghost(tmp_path):
    skill = {
        "id": "fill-the-gap", "name": "Gap", "kind": "capability",
        "description": "cubre el hueco", "tags": ["x"], "prompt": "haz X. Devuelve JSON.",
    }
    fac = _factory(tmp_path, BAD_SPEC, claude_out=json.dumps(skill))
    report = await fac.build("algo imposible", escalate=True)
    assert report.ok is False
    assert report.proposal is not None
    assert report.proposal["status"] == "pending"
    # la propuesta quedó en staging, NO aplicada al Skill Master
    assert fac.skills.get("fill-the-gap") is None
    assert fac.ghost.pending()
