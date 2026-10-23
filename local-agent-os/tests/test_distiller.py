from __future__ import annotations

import json

import pytest

import agent_os.core.agent as core_agent
from agent_os.factory.distiller import AgentDistiller
from agent_os.factory.loader import ConstructedAgent
from agent_os.factory.spec import AgentSpec

SPEC = AgentSpec(
    id="investigador",
    name="Investigador",
    description="Resume páginas.",
    reads=["url"],
    writes="research",
    output_schema={"resumen": "str"},
    tools=["http_get"],
    prompt="Eres un investigador. Devuelve solo JSON con resumen.",
    evals=[{"input": {"url": "https://a.com"}, "expect": {"writes": "research"}}],
)


@pytest.fixture(autouse=True)
def _restore():
    original = core_agent.chat_json
    yield
    core_agent.chat_json = original


def _set_model(response):
    async def fake_chat(model, system, user):
        return response(user) if callable(response) else response

    core_agent.chat_json = fake_chat


def _agent():
    return ConstructedAgent(SPEC)


@pytest.mark.asyncio
async def test_generate_keeps_only_verified(tmp_path):
    # válido para url=a.com, inválido (sin 'resumen') para el resto
    _set_model(lambda user: {"resumen": "ok"} if "a.com" in user else {"otro": 1})
    d = AgentDistiller(datasets_dir=tmp_path)
    examples = await d.generate(_agent(), [{"url": "https://a.com"}, {"url": "https://b.com"}])
    assert len(examples) == 1
    assert examples[0].input == {"url": "https://a.com"}
    assert examples[0].source == "master:verified"


@pytest.mark.asyncio
async def test_dataset_chat_format(tmp_path):
    _set_model({"resumen": "ok"})
    d = AgentDistiller(datasets_dir=tmp_path)
    agent = _agent()
    examples = await d.generate(agent, [{"url": "https://a.com"}])
    rows = d.to_chat_dataset(agent, examples)
    msgs = rows[0]["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant"]
    assert msgs[0]["content"] == agent.system_prompt
    assert "url: https://a.com" in msgs[1]["content"]
    assert json.loads(msgs[2]["content"]) == {"resumen": "ok"}


@pytest.mark.asyncio
async def test_write_dataset(tmp_path):
    _set_model({"resumen": "ok"})
    d = AgentDistiller(datasets_dir=tmp_path)
    agent = _agent()
    examples = await d.generate(agent, [{"url": "https://a.com"}, {"url": "https://a.com"}])
    path = d.write_dataset(agent.contract.id, d.to_chat_dataset(agent, examples))
    assert path.exists()
    assert len(path.read_text().strip().splitlines()) == 2


@pytest.mark.asyncio
async def test_evaluate_passes_and_fails(tmp_path):
    _set_model({"resumen": "ok"})
    d = AgentDistiller(datasets_dir=tmp_path)
    agent = _agent()
    good = await d.evaluate(agent, [{"input": {"url": "x"}, "expect": {"writes": "research"}}])
    assert good.score == 1.0 and good.passed == 1
    bad = await d.evaluate(agent, [{"input": {"url": "x"}, "expect": {"resumen": "otra-cosa"}}])
    assert bad.score == 0.0


@pytest.mark.asyncio
async def test_distill_report(tmp_path):
    _set_model({"resumen": "ok"})
    d = AgentDistiller(datasets_dir=tmp_path)
    report = await d.distill(_agent(), [{"url": "https://a.com"}] * 3, min_examples=2)
    assert report.examples == 3
    assert report.ready_to_train is True
    assert report.dataset_path and "investigador.jsonl" in report.dataset_path
    assert "train_mlx.sh investigador" in report.train_command


@pytest.mark.asyncio
async def test_promote_if_ready(tmp_path):
    from agent_os.factory.entrenador import Entrenador
    _set_model({"resumen": "ok"})
    ent = Entrenador(models_file=tmp_path / "models.json")
    d = AgentDistiller(entrenador=ent, datasets_dir=tmp_path)
    res = await d.promote_if_ready(_agent(), "agent-os/investigador:v1")
    assert res["promoted"] is True
    assert ent.status("investigador")["specialized"] is True
