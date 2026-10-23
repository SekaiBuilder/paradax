from __future__ import annotations

import pytest

import agent_os.core.agent as core_agent
import agent_os.factory.distiller as dist_mod
import agent_os.factory.entrenador as ent_mod
from agent_os.factory.distiller import AgentDistiller
from agent_os.factory.entrenador import Entrenador
from agent_os.factory.loader import ConstructedAgent
from agent_os.factory.spec import AgentSpec


def _agent():
    return ConstructedAgent(AgentSpec(
        id="redactor", name="Redactor", description="escribe copy",
        reads=["tema"], writes="copy", output_schema={"texto": "str"},
        prompt="Eres un redactor. Devuelve solo JSON con texto.",
    ))


@pytest.fixture(autouse=True)
def _tmp_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(ent_mod, "TRAINING_QUEUE_DIR", tmp_path / "queue")
    monkeypatch.setattr(dist_mod, "DATASETS_DIR", tmp_path / "datasets")


def _set(monkeypatch, synth=None, agent_out=None):
    if synth is not None:
        async def fake_synth(model, system, user):
            return synth
        monkeypatch.setattr(dist_mod, "chat_json", fake_synth)
    if agent_out is not None:
        async def fake_agent(model, system, user):
            return agent_out
        monkeypatch.setattr(core_agent, "chat_json", fake_agent)


@pytest.mark.asyncio
async def test_synthesize_inputs_filters_bad(monkeypatch, tmp_path):
    _set(monkeypatch, synth={"inputs": [{"tema": "a"}, {"otra": 1}, {"tema": "b"}]})
    d = AgentDistiller(datasets_dir=tmp_path / "ds")
    inputs = await d.synthesize_inputs(_agent(), "foco legal", "", n=6, model="m")
    assert inputs == [{"tema": "a"}, {"tema": "b"}]  # descarta el que no trae 'tema'


@pytest.mark.asyncio
async def test_run_training_produces_dataset(monkeypatch):
    _set(monkeypatch, synth={"inputs": [{"tema": "x"}, {"tema": "y"}]}, agent_out={"texto": "ok"})
    ent = Entrenador()
    agent = _agent()
    await ent.refine(agent, focus="dominio legal")        # encola
    brief = await ent.run_training(agent, model="m")       # dispara destilación real
    assert brief["status"] == "dataset-listo"
    assert brief["dataset"]["inputs_sintetizados"] == 2
    assert brief["dataset"]["ejemplos_verificados"] == 2   # ambos pasan el schema
    assert "redactor.jsonl" in brief["dataset"]["path"]
    assert "train_mlx.sh redactor" in brief["dataset"]["train_command"]


@pytest.mark.asyncio
async def test_run_training_requires_queued(monkeypatch):
    _set(monkeypatch, synth={"inputs": []}, agent_out={"texto": "ok"})
    with pytest.raises(ValueError):
        await Entrenador().run_training(_agent(), model="m")  # nada encolado


@pytest.mark.asyncio
async def test_dequeue(monkeypatch):
    ent = Entrenador()
    await ent.refine(_agent(), focus="x")
    assert ent.dequeue("redactor") is True
    assert ent.training_queue() == []
