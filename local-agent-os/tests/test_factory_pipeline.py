from __future__ import annotations

import pytest

import agent_os.core.agent as core_agent
from agent_os.factory.auditor import Auditor
from agent_os.factory.loader import DynamicRegistry, build_output_model
from agent_os.factory.spec import AgentSpec
from agent_os.factory.validator import Validador


def _spec(**over) -> AgentSpec:
    base = dict(
        id="investigador",
        name="Investigador",
        description="Resume páginas.",
        reads=["url"],
        writes="research",
        output_schema={"resumen": "str", "hallazgos": "list[str]"},
        skills=[],
        tools=["http_get"], uses_tools=True,
        prompt="Eres un investigador. Devuelve solo JSON con resumen y hallazgos.",
        uses_llm=True,
        max_retries=1,
        evals=[{"input": {"url": "https://ej.com"}, "expect": {"writes": "research"}}],
    )
    base.update(over)
    return AgentSpec(**base)


def _patch_model(monkeypatch, response: dict):
    async def fake_chat(model, system, user):
        return response

    monkeypatch.setattr(core_agent, "chat_json", fake_chat)


# ── Auditor ──────────────────────────────────────────────────────────────────
def test_auditor_passes_valid_spec():
    report = Auditor().audit(_spec(), taken_ids=["action_planner"])
    assert report.ok
    assert report.issues == []


def test_auditor_flags_duplicate_id():
    report = Auditor().audit(_spec(id="action_planner"), taken_ids=["action_planner"])
    assert not report.ok
    assert any("ya existe" in i for i in report.issues)


def test_auditor_flags_llm_without_schema():
    report = Auditor().audit(_spec(output_schema={}))
    assert not report.ok


def test_auditor_flags_non_identifier_field():
    report = Auditor().audit(_spec(output_schema={"mi campo": "str"}))
    assert not report.ok
    assert any("identificador" in i for i in report.issues)


def test_auditor_warns_when_no_evals():
    report = Auditor().audit(_spec(evals=[]))
    assert report.ok  # warning, no bloquea
    assert report.warnings


# ── Loader ───────────────────────────────────────────────────────────────────
def test_build_output_model_enforces_schema():
    Model = build_output_model(_spec())
    ok = Model.model_validate({"resumen": "hola", "hallazgos": ["a", "b"]})
    assert ok.resumen == "hola"
    with pytest.raises(Exception):
        Model.model_validate({"resumen": "hola"})  # falta 'hallazgos'


@pytest.mark.asyncio
async def test_constructed_agent_runs(monkeypatch, tmp_path):
    _patch_model(monkeypatch, {"resumen": "ok", "hallazgos": ["x"]})
    reg = DynamicRegistry(root=tmp_path / "specs")
    agent = reg.register(_spec(tools=[], uses_tools=False))  # agente que solo razona
    out = await agent.run({"url": "https://ej.com"})
    assert out.resumen == "ok"
    assert out.hallazgos == ["x"]


def test_registry_persist_and_reload(tmp_path):
    reg = DynamicRegistry(root=tmp_path / "specs")
    reg.register(_spec())
    assert (tmp_path / "specs" / "investigador.json").exists()
    reg2 = DynamicRegistry(root=tmp_path / "specs")
    assert reg2.load_all() == 1
    assert reg2.ids() == ["investigador"]


def test_registry_unregister(tmp_path):
    reg = DynamicRegistry(root=tmp_path / "specs")
    reg.register(_spec())
    assert reg.unregister("investigador") is True
    assert reg.get("investigador") is None
    assert not (tmp_path / "specs" / "investigador.json").exists()


# ── Validador ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_validator_passes_good_spec():
    verdict = await Validador().validate(_spec(), taken_ids=["action_planner"])
    assert verdict.ok and verdict.built
    assert verdict.reason == "apto ✓"


@pytest.mark.asyncio
async def test_validator_fails_on_non_compiling_schema():
    # nombre de campo con espacio: AgentSpec lo acepta, pero create_model no.
    verdict = await Validador().validate(_spec(output_schema={"mal nombre": "str"}))
    assert not verdict.ok
    assert not verdict.built or verdict.audit.issues


@pytest.mark.asyncio
async def test_validator_runs_evals(monkeypatch):
    _patch_model(monkeypatch, {"resumen": "ok", "hallazgos": ["x"]})
    verdict = await Validador().validate(_spec(), run_evals=True)
    assert verdict.ok
    assert verdict.evals and all(e.ok for e in verdict.evals)
