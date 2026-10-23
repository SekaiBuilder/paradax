from __future__ import annotations

import httpx
import pytest

import agent_os.core.agent as core_agent
import agent_os.db as db
import agent_os.orchestrator as orch
from agent_os.tools import media

HTML = '<button id="btn-kanji" class="nav-btn">Kanji</button><div id="tut-x"></div>'

PLAN = {
    "reasoning_summary": "demo",
    "actions_file_name": "acciones-kanji.json",
    "gif_output_name": "kanji.gif",
    "actions": [
        {"accion": "esperar", "ms": 1000},
        {"accion": "click", "selector": ".ck-accept-btn"},
        {"accion": "esperar", "ms": 2500},
        {"accion": "click", "selector": "#tut-x"},
        {"accion": "esperar", "ms": 500},
        {"accion": "marcar"},
        {"accion": "click", "selector": "#btn-kanji"},
        {"accion": "esperar", "ms": 1500},
    ],
}


def test_media_intent_guard_accepts_kana_media_requests():
    assert orch.is_media_request("haz un gif del kanji 水")
    assert orch.is_media_request("solo un gif de hiragana")
    assert orch.is_media_request("quiero un reel del quiz de katakana")


def test_media_intent_guard_rejects_code_tasks():
    assert not orch.is_media_request("reprograma Paradax para mejorar el grafico del proyecto")
    assert not orch.is_media_request("actualiza la vision grafica de Paradax y cambia el codigo")


@pytest.fixture
def wired(monkeypatch, tmp_path, gif_ok, gif_broken):
    """Pipeline completo con LLM y herramientas falsas. La primera grabación
    sale rota (pasos fallidos) y la segunda bien → ejercita la reparación."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.sqlite3")
    monkeypatch.setattr(orch, "RUNS_DIR", tmp_path / "runs")

    async def fake_chat(model, system, user):
        if "ScriptWriterAgent" in system:
            return {"voice_script": "こんにちは皆さん. Demo del 漢字 水. Enlace en la bio."}
        return PLAN

    monkeypatch.setattr(core_agent, "chat_json", fake_chat)

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, text=HTML, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    monkeypatch.setattr(
        media, "active_project",
        lambda: {"name": "kana-trainer", "path": "/tmp/p.md", "url": "https://kana.example.com"},
    )
    monkeypatch.setattr(media, "write_actions", lambda name, actions: f"/tmp/{name}")

    recordings = {"n": 0}

    def fake_record(url, actions_file, output_name):
        recordings["n"] += 1
        result = dict(gif_broken if recordings["n"] == 1 else gif_ok)
        result["path"] = f"/tmp/{output_name}"
        return result

    monkeypatch.setattr(media, "record_page_gif", fake_record)
    monkeypatch.setattr(
        media, "make_reel",
        lambda gif, script, lang, music, name: {
            "path": f"/tmp/{name}",
            "verification": {"exists": True, "path": f"/tmp/{name}", "duration": 12.0, "size": 2_000_000, "ok": True},
        },
    )
    return recordings


@pytest.mark.asyncio
async def test_full_pipeline_with_repair(wired):
    req = orch.MediaRunRequest(request="haz un reel del kanji 水", language="es")
    output = await orch.run_media_manager(req)

    assert wired["n"] == 2, "GIF roto → un único reintento de grabación"
    assert output["repaired"] is True
    assert output["verdict"]["ok"] is True
    assert "repair-" in output["gif"]["path"]
    assert output["reel"]["path"].endswith("-es.mp4")
    assert output["plan_source"] == "model"

    run = db.get_run(output["run_id"])
    assert run["status"] == "completed"
    kinds = [e["kind"] for e in run["events"]]
    agents_done = [
        e["payload"]["agent"] for e in run["events"] if e["kind"] == "agent_completed"
    ]
    assert agents_done == [
        "page_inspector",
        "action_planner",
        "browser_recorder",
        "verifier",
        "browser_recorder",  # reparación
        "verifier",
        "script_writer",
        "video_builder",
    ]
    assert "gif_repair_started" in kinds


@pytest.mark.asyncio
async def test_pipeline_without_reel_skips_writer_and_builder(wired, gif_ok):
    req = orch.MediaRunRequest(request="solo un gif de hiragana", make_reel=False)
    output = await orch.run_media_manager(req)

    assert "reel" not in output
    run = db.get_run(output["run_id"])
    agents_done = [
        e["payload"]["agent"] for e in run["events"] if e["kind"] == "agent_completed"
    ]
    assert "script_writer" not in agents_done
    assert "video_builder" not in agents_done


@pytest.mark.asyncio
async def test_pipeline_rejects_non_media_request_before_loading_project(monkeypatch):
    loaded = False

    def fake_active_project():
        nonlocal loaded
        loaded = True
        return {"name": "kana-trainer", "path": "/tmp/p.md", "url": "https://kana.example.com"}

    monkeypatch.setattr(media, "active_project", fake_active_project)

    with pytest.raises(orch.UnsupportedMediaRequest):
        await orch.run_media_manager(
            orch.MediaRunRequest(request="reprograma la interfaz de Paradax", make_reel=False)
        )

    assert loaded is False
