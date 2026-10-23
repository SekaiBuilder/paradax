from __future__ import annotations

import pytest

import agent_os.core.agent as core_agent
from agent_os.core.agent import AgentError
from agent_os.factory.constructor import ConstructorAgent

VALID_SPEC = {
    "id": "investigador_competencia",
    "name": "Investigador de competencia",
    "description": "Resume páginas de la competencia.",
    "reads": ["url"],
    "writes": "research",
    "output_schema": {"resumen": "str", "hallazgos": "list[str]"},
    "skills": ["web-selectors"],
    "tools": ["http_get"], "uses_tools": True,
    "prompt": "Eres un investigador. Recibes la entrada del contexto, la analizas paso a paso según la tarea descrita, aplicas criterios claros y verificables y respondes con los campos del schema. Devuelve solo JSON.",
    "uses_llm": True,
    "max_retries": 1,
    "evals": [],
}


@pytest.fixture
def ctx():
    return {
        "request": "necesito un agente que investigue la competencia",
        "skills_catalog": [
            {"id": "web-selectors", "name": "Selectores reales", "description": "ids reales", "tags": ["web"]},
        ],
        "taken_ids": ["page_inspector", "action_planner"],
        "model": "qwen3-coder:30b",
    }


def _patch_model(monkeypatch, responses):
    calls = {"n": 0}

    async def fake_chat(model, system, user):
        i = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        r = responses[i]
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(core_agent, "chat_json", fake_chat)
    return calls


@pytest.mark.asyncio
async def test_valid_spec_passes(monkeypatch, ctx):
    _patch_model(monkeypatch, [VALID_SPEC])
    spec = await ConstructorAgent().run(ctx)
    assert spec.id == "investigador_competencia"
    assert spec.writes == "research"
    assert spec.created_by == "constructor"


@pytest.mark.asyncio
async def test_invented_tool_rejected_then_retried(monkeypatch, ctx):
    bad = dict(VALID_SPEC, tools=["http_get", "tool_que_no_existe"])
    calls = _patch_model(monkeypatch, [bad, VALID_SPEC])
    spec = await ConstructorAgent().run(ctx)
    assert calls["n"] == 2, "debe reintentar tras rechazar la tool inventada"
    assert spec.tools == ["http_get"]


@pytest.mark.asyncio
async def test_invented_skill_rejected(monkeypatch, ctx):
    bad = dict(VALID_SPEC, skills=["skill_inexistente"])
    calls = _patch_model(monkeypatch, [bad, VALID_SPEC])
    await ConstructorAgent().run(ctx)
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_duplicate_id_rejected(monkeypatch, ctx):
    dup = dict(VALID_SPEC, id="action_planner")  # ya existe en taken_ids
    calls = _patch_model(monkeypatch, [dup, VALID_SPEC])
    spec = await ConstructorAgent().run(ctx)
    assert calls["n"] == 2
    assert spec.id == "investigador_competencia"


@pytest.mark.asyncio
async def test_llm_agent_without_output_schema_rejected(monkeypatch, ctx):
    bad = dict(VALID_SPEC, output_schema={})
    calls = _patch_model(monkeypatch, [bad, VALID_SPEC])
    await ConstructorAgent().run(ctx)
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_bad_type_in_schema_then_fail(monkeypatch, ctx):
    bad = dict(VALID_SPEC, output_schema={"x": "tipo_invalido"})
    # ambas respuestas inválidas → agota reintentos → AgentError (sin fallback)
    _patch_model(monkeypatch, [bad, bad, bad])
    with pytest.raises(AgentError):
        await ConstructorAgent().run(ctx)


def test_hollow_prompt_rejected():
    from agent_os.factory.spec import AgentSpec
    from agent_os.factory.constructor import MIN_PROMPT_CHARS
    spec = AgentSpec(id="hueco", name="Hueco", writes="out", output_schema={"a": "str"},
                     prompt="Eres un analizador. Devuelve solo JSON.")
    assert "prompt demasiado corto" in ConstructorAgent().semantic_check(spec, {})
    assert len(spec.prompt) < MIN_PROMPT_CHARS


def test_declared_tools_without_uses_tools_is_rejected():
    """Declarar tools con uses_tools=false las deja sin ejecutar nunca: se rechaza con motivo."""
    from agent_os.factory.auditor import Auditor
    from agent_os.factory.spec import AgentSpec
    base = dict(VALID_SPEC)
    base.pop("uses_tools", None)
    spec = AgentSpec(**base, uses_tools=False)
    assert any("uses_tools=false" in i for i in Auditor().audit(spec).issues)
    assert "uses_tools=false" in ConstructorAgent().semantic_check(spec, {"skills_catalog": [], "taken_ids": []})
    ok = AgentSpec(**base, uses_tools=True)
    assert not any("uses_tools" in i for i in Auditor().audit(ok).issues)
    thinker = AgentSpec(**{**base, "tools": []}, uses_tools=False)
    assert not any("uses_tools" in i for i in Auditor().audit(thinker).issues)
