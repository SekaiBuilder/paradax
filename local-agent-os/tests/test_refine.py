from __future__ import annotations

import pytest

import agent_os.factory.entrenador as ent_mod
from agent_os.factory.entrenador import Entrenador
from agent_os.factory.loader import ConstructedAgent
from agent_os.factory.spec import AgentSpec


def _agent():
    return ConstructedAgent(AgentSpec(
        id="redactor", name="Redactor", description="escribe copy",
        reads=["url"], writes="copy", output_schema={"texto": "str"},
        skills=["web-selectors", "voice-script-es"], tools=[],
        prompt="Eres un redactor. Devuelve solo JSON con texto.",
    ))


@pytest.fixture(autouse=True)
def _tmp_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(ent_mod, "TRAINING_QUEUE_DIR", tmp_path / "queue")


@pytest.mark.asyncio
async def test_refine_without_material(tmp_path):
    brief = await Entrenador().refine(_agent(), focus="tono más formal")
    assert brief["agent_id"] == "redactor"
    assert brief["focus"] == "tono más formal"
    assert brief["skills"] == ["web-selectors", "voice-script-es"]
    assert brief["material"] is None
    assert brief["status"] == "queued"
    assert (ent_mod.TRAINING_QUEUE_DIR / "redactor.json").exists()


@pytest.mark.asyncio
async def test_refine_with_text_material(tmp_path):
    f = tmp_path / "guia.txt"
    f.write_text("guía de estilo: usa frases cortas", encoding="utf-8")
    brief = await Entrenador().refine(_agent(), focus="estilo", material_source=str(f))
    assert brief["material"]["kind"] == "text"
    assert brief["material"]["chars"] > 0
    assert "frases cortas" in brief["material"]["preview"]


@pytest.mark.asyncio
async def test_training_queue_lists_briefs():
    ent = Entrenador()
    await ent.refine(_agent(), focus="a")
    queue = ent.training_queue()
    assert [b["agent_id"] for b in queue] == ["redactor"]
    assert queue[0]["plan"]  # incluye la receta de entrenamiento
