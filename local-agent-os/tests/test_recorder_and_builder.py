from __future__ import annotations

import pytest

from agent_os.agents.browser_recorder import BrowserRecorderAgent
from agent_os.agents.video_builder import VideoBuilderAgent
from agent_os.tools import media


@pytest.mark.asyncio
async def test_recorder_writes_actions_then_records(monkeypatch, gif_ok):
    written = {}

    def fake_write(name, actions):
        written["name"] = name
        written["actions"] = actions
        return f"/tmp/{name}"

    def fake_record(url, actions_file, output_name):
        written["recorded"] = (url, actions_file, output_name)
        return gif_ok

    monkeypatch.setattr(media, "write_actions", fake_write)
    monkeypatch.setattr(media, "record_page_gif", fake_record)

    plan = {
        "actions_file_name": "acciones-x.json",
        "gif_output_name": "x.gif",
        "actions": [{"accion": "marcar"}],
    }
    out = await BrowserRecorderAgent().run({"url": "https://kana.example.com", "plan": plan})

    assert written["name"] == "acciones-x.json"
    assert written["recorded"] == ("https://kana.example.com", "/tmp/acciones-x.json", "x.gif")
    assert out.verification.ok is True


@pytest.mark.asyncio
async def test_builder_names_reel_from_actual_gif(monkeypatch, gif_ok):
    captured = {}

    def fake_make_reel(gif_path, script, language, music, output_name):
        captured["output_name"] = output_name
        return {
            "path": f"/tmp/{output_name}",
            "verification": {"exists": True, "path": f"/tmp/{output_name}", "duration": 12.0, "size": 2_000_000, "ok": True},
        }

    monkeypatch.setattr(media, "make_reel", fake_make_reel)

    # GIF reparado: el nombre del reel debe derivar del GIF real usado.
    gif_ok["path"] = "/tmp/repair-kanji-6c34-run99.gif"
    out = await VideoBuilderAgent().run(
        {
            "gif": gif_ok,
            "voice": {"language": "es", "text": "guion de prueba suficientemente largo"},
            "language": "es",
            "music": "_placeholder-koto.mp3",
        }
    )
    assert captured["output_name"] == "reel-repair-kanji-6c34-run99-es.mp4"
    assert out.verification.ok is True
