from __future__ import annotations

import json

import pytest

import agent_os.training.evaluator as ev

GOOD_COMPACT = {
    "f": "acciones-kanji.json",
    "g": "kanji.gif",
    "a": [
        ["w", 1000], ["c", ".ck-accept-btn"], ["w", 2500], ["c", "#tut-x"],
        ["w", 500], ["m"], ["c", "#btn-kanji"], ["w", 1500],
    ],
}

INVENTORY = {
    "url": "https://kana.example.com",
    "fetched": True,
    "ids": ["btn-kanji", "tut-x"],
    "classes": ["ck-accept-btn"],
    "data_selectors": [],
}

CASE = {"request": "gif del kanji 水", "inventory": INVENTORY, "compact_plan": GOOD_COMPACT}


def test_good_plan_passes_all_checks():
    checks = ev.score_plan(GOOD_COMPACT, INVENTORY)
    assert all(checks.values()), checks


def test_invented_selector_fails_selectors_check():
    bad = dict(GOOD_COMPACT, a=GOOD_COMPACT["a"] + [["c", "#no-existe-xyz"], ["w", 1500]])
    checks = ev.score_plan(bad, INVENTORY)
    assert checks["selectors"] is False
    assert checks["wire"] is True


def test_garbage_fails_wire_not_crashes():
    checks = ev.score_plan({"f": "x.json"}, INVENTORY)
    assert checks["wire"] is False
    assert not any(v for k, v in checks.items() if k != "parses")


def test_bad_tail_and_waits_detected():
    bad = dict(GOOD_COMPACT, a=[["w", 100], ["m"], ["c", "#btn-kanji"]])
    checks = ev.score_plan(bad, INVENTORY)
    assert checks["waits"] is False
    assert checks["tail"] is False


@pytest.mark.asyncio
async def test_evaluate_model_aggregates(monkeypatch):
    async def fake_chat(model, system, user):
        return GOOD_COMPACT

    monkeypatch.setattr(ev, "chat_json", fake_chat)
    report = await ev.evaluate_model("fake:3b", [CASE, CASE])
    assert report["score"] == 1.0
    assert report["perfect"] == 1.0
    assert report["failures"] == []
    assert ev.should_promote(report)


@pytest.mark.asyncio
async def test_model_error_scores_zero(monkeypatch):
    async def fake_chat(model, system, user):
        raise RuntimeError("modelo caído")

    monkeypatch.setattr(ev, "chat_json", fake_chat)
    report = await ev.evaluate_model("fake:3b", [CASE])
    assert report["score"] == 0.0
    assert not ev.should_promote(report)
    assert report["failures"][0]["failed"]


def test_promote_writes_models_map(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "MODELS_FILE", tmp_path / "models.json")
    ev.promote("action_planner", "agent-os/action-planner:v1")
    ev.promote("script_writer", "agent-os/script-writer:v1")
    data = json.loads((tmp_path / "models.json").read_text())
    assert data == {
        "action_planner": "agent-os/action-planner:v1",
        "script_writer": "agent-os/script-writer:v1",
    }
