from __future__ import annotations

import pytest

import agent_os.core.agent as core_agent
from agent_os.factory.factory import AgentFactory
from agent_os.factory.ghost import Ghost
from agent_os.factory.loader import DynamicRegistry
from agent_os.factory.project import ProjectStore
from agent_os.factory.project_manager import ProjectManager
from agent_os.factory.skill_master import SkillMaster

TEAM = {
    "reasoning_summary": "equipo mínimo",
    "agents": [
        {"name": "Redactor", "role": "escribe copy"},
        {"name": "Hashtagger", "role": "propone hashtags"},
    ],
}
BRIEFS = {
    "briefs": [
        {"agent_name": "Redactor", "need": "escribe copy corto para un post", "skills": [], "tools": []},
        {"agent_name": "Hashtagger", "need": "propón hashtags por idioma", "skills": [], "tools": []},
    ]
}
SPEC_A = {
    "id": "redactor_copy", "name": "Redactor de copy", "description": "escribe copy",
    "reads": ["url"], "writes": "copy", "output_schema": {"texto": "str"},
    "tools": [], "skills": [], "prompt": "Eres un redactor. Recibes la entrada del contexto, la analizas paso a paso según la tarea descrita, aplicas criterios claros y verificables y respondes con los campos del schema. Devuelve solo JSON con texto.",
    "uses_llm": True, "evals": [],
}
SPEC_B = {
    "id": "hashtagger", "name": "Hashtagger", "description": "propone hashtags",
    "reads": ["url"], "writes": "hashtags", "output_schema": {"lista": "list[str]"},
    "tools": [], "skills": [], "prompt": "Eres un experto en hashtags. Recibes la entrada del contexto, la analizas paso a paso según la tarea descrita, aplicas criterios claros y verificables y respondes con los campos del schema. Devuelve solo JSON con lista.",
    "uses_llm": True, "evals": [],
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


def _pm(tmp_path):
    factory = AgentFactory(
        skill_master=SkillMaster(root=tmp_path / "skills"),
        registry=DynamicRegistry(root=tmp_path / "specs"),
        ghost=Ghost(call_claude=lambda p: None, staging=tmp_path / "staging"),
    )
    return ProjectManager(store=ProjectStore(root=tmp_path / "projects"), factory=factory)


@pytest.mark.asyncio
async def test_build_team_end_to_end(tmp_path):
    _seq([TEAM, BRIEFS, SPEC_A, SPEC_B])
    pm = _pm(tmp_path)
    project = pm.store.create("Social Media Manager", goal="publicar reels a diario")
    built = await pm.build_team(project, model="m")
    assert built.status == "ready"
    assert built.agents == ["redactor_copy", "hashtagger"]
    assert built.team_plan and len(built.team_plan["agents"]) == 2
    assert len(built.briefs) == 2
    # los agentes quedaron registrados y etiquetados con el proyecto
    assert pm.factory.registry.get("redactor_copy").spec.project == built.id
    assert any("✅ proyecto listo" in line for line in built.log)


@pytest.mark.asyncio
async def test_build_team_fails_when_planner_fails(tmp_path):
    _seq([{"agents": []}])  # team plan inválido (min_length=1) → planner agota reintentos
    pm = _pm(tmp_path)
    project = pm.store.create("Roto", goal="objetivo imposible")
    built = await pm.build_team(project, model="m")
    assert built.status == "failed"
    assert any("Team Planner" in line for line in built.log)


@pytest.mark.asyncio
async def test_partial_build_still_ready(tmp_path):
    # segundo spec inválido (schema no compila) → solo 1 agente, pero ready
    bad_b = dict(SPEC_B, output_schema={"mal nombre": "str"})
    _seq([TEAM, BRIEFS, SPEC_A, bad_b, bad_b, bad_b])
    pm = _pm(tmp_path)
    project = pm.store.create("Parcial", goal="x")
    built = await pm.build_team(project, model="m")
    assert built.status == "ready"
    assert built.agents == ["redactor_copy"]
