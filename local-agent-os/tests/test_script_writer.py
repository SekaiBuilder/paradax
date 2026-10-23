from __future__ import annotations

import pytest

import agent_os.core.agent as core_agent
from agent_os.agents.script_writer import ScriptWriterAgent


def _patch_model(monkeypatch, response):
    async def fake_chat(model, system, user):
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(core_agent, "chat_json", fake_chat)


@pytest.mark.asyncio
async def test_model_script_used(monkeypatch):
    _patch_model(monkeypatch, {"voice_script": "こんにちは皆さん. Hoy vemos el 漢字 水. Pruébala gratis, enlace en la bio."})
    out = await ScriptWriterAgent().run(
        {"request": "reel del kanji 水", "language": "es", "model": "m"}
    )
    assert out.source == "model"
    assert "水" in out.text


@pytest.mark.asyncio
async def test_model_error_falls_back_with_kanji_template(monkeypatch):
    _patch_model(monkeypatch, RuntimeError("timeout"))
    out = await ScriptWriterAgent().run(
        {"request": "reel del kanji 水", "language": "en", "model": "m"}
    )
    assert out.source.startswith("fallback:")
    assert "水" in out.text
    assert "link in bio" in out.text


@pytest.mark.asyncio
async def test_too_short_script_falls_back(monkeypatch):
    _patch_model(monkeypatch, {"voice_script": "hola"})  # <10 chars: schema lo rechaza
    out = await ScriptWriterAgent().run(
        {"request": "un reel cualquiera", "language": "it", "model": "m"}
    )
    assert out.source.startswith("fallback:")
    assert out.language == "it"
