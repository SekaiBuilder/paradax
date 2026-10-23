from __future__ import annotations

import pytest

import agent_os.core.agent as core_agent
from agent_os.factory.skills_definer import SkillsDefinerAgent
from agent_os.factory.team_planner import TeamPlannerAgent

TEAM = {
    "reasoning_summary": "equipo mínimo",
    "agents": [
        {"name": "Redactor", "role": "escribe copy"},
        {"name": "Hashtagger", "role": "propone hashtags"},
    ],
}
BRIEFS = {
    "briefs": [
        {"agent_name": "Redactor", "need": "escribe copy corto", "skills": ["voice-script-es"], "tools": []},
        {"agent_name": "Hashtagger", "need": "propón hashtags", "skills": [], "tools": []},
    ]
}


@pytest.fixture(autouse=True)
def _restore():
    original = core_agent.chat_json
    yield
    core_agent.chat_json = original


def _seq(responses):
    state = {"n": 0}

    async def fake(model, system, user):
        i = min(state["n"], len(responses) - 1)
        state["n"] += 1
        return responses[i]

    core_agent.chat_json = fake
    return state


@pytest.mark.asyncio
async def test_team_planner_valid():
    _seq([TEAM])
    plan = await TeamPlannerAgent().run({"goal": "gestionar redes", "model": "m"})
    assert [a.name for a in plan.agents] == ["Redactor", "Hashtagger"]


@pytest.mark.asyncio
async def test_team_planner_rejects_too_many():
    big = {"agents": [{"name": f"A{i}", "role": "x"} for i in range(9)]}
    calls = _seq([big, TEAM])
    plan = await TeamPlannerAgent().run({"goal": "x", "model": "m"})
    assert calls["n"] == 2
    assert len(plan.agents) == 2


@pytest.mark.asyncio
async def test_skills_definer_valid():
    _seq([BRIEFS])
    ctx = {
        "goal": "redes", "team_plan": TEAM, "model": "m",
        "skills_catalog": [{"id": "voice-script-es", "name": "Voz", "description": "guion"}],
    }
    out = await SkillsDefinerAgent().run(ctx)
    assert [b.agent_name for b in out.briefs] == ["Redactor", "Hashtagger"]


@pytest.mark.asyncio
async def test_skills_definer_rejects_invented_skill():
    bad = {"briefs": [{"agent_name": "Redactor", "need": "x", "skills": ["inexistente"], "tools": []}]}
    calls = _seq([bad, BRIEFS])
    ctx = {
        "goal": "redes", "team_plan": TEAM, "model": "m",
        "skills_catalog": [{"id": "voice-script-es", "name": "Voz", "description": "guion"}],
    }
    await SkillsDefinerAgent().run(ctx)
    assert calls["n"] == 2
