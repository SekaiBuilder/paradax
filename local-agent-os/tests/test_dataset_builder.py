from __future__ import annotations

import json
import sqlite3

import pytest

from agent_os.training import dataset_builder as dsb

PLAN = {
    "reasoning_summary": "demo",
    "actions_file_name": "acciones-kanji.json",
    "gif_output_name": "kanji.gif",
    "actions": [
        {"accion": "esperar", "ms": 1000},
        {"accion": "click", "selector": ".ck-accept-btn"},
        {"accion": "marcar"},
        {"accion": "click", "selector": "#btn-kanji"},
        {"accion": "esperar", "ms": 1500},
    ],
    "plan_source": "model",
    "discarded_actions": 0,
}

INVENTORY = {
    "url": "https://kana.example.com",
    "fetched": True,
    "ids": ["btn-kanji"],
    "classes": ["ck-accept-btn"],
    "data_selectors": [],
    "note": "",
}


def _seed_run(conn, run_id, request, *, verdict_ok=True, repaired=False, source="model", status="completed"):
    conn.execute(
        "INSERT INTO runs (id, agent, status, request, created_at, updated_at) VALUES (?, 'media_manager', ?, ?, '2026-06-12', '2026-06-12')",
        (run_id, status, request),
    )

    def ev(kind, payload):
        conn.execute(
            "INSERT INTO run_events (run_id, kind, payload_json, created_at) VALUES (?, ?, ?, '2026-06-12')",
            (run_id, kind, json.dumps(payload, ensure_ascii=False)),
        )

    plan = dict(PLAN, plan_source=source)
    ev("agent_completed", {"agent": "page_inspector", "output": INVENTORY})
    ev("agent_completed", {"agent": "action_planner", "output": plan})
    ev("agent_completed", {"agent": "verifier", "output": {"ok": verdict_ok, "target": "/tmp/x.gif", "should_repair": not verdict_ok}})
    if repaired:
        ev("gif_repair_started", {"reason": "pasos fallidos"})
        ev("agent_completed", {"agent": "verifier", "output": {"ok": True, "target": "/tmp/y.gif", "should_repair": False}})


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE runs (id TEXT PRIMARY KEY, agent TEXT, status TEXT, request TEXT, model TEXT, output_json TEXT, error TEXT, created_at TEXT, updated_at TEXT)")
    conn.execute("CREATE TABLE run_events (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, kind TEXT, payload_json TEXT, created_at TEXT)")
    yield path, conn
    conn.close()


def test_only_verified_unrepaired_runs_enter(db):
    path, conn = db
    _seed_run(conn, "r1", "gif del kanji 水")
    _seed_run(conn, "r2", "gif del kanji 月", verdict_ok=False, repaired=True)
    _seed_run(conn, "r3", "gif del kanji 日", verdict_ok=False)
    conn.commit()

    examples = dsb.harvest(path)
    assert [e["run_id"] for e in examples] == ["r1"]


def test_repair_source_excluded_fallback_included(db):
    path, conn = db
    _seed_run(conn, "r1", "gif de hiragana", source="fallback:model_error:timeout")
    _seed_run(conn, "r2", "gif de katakana", source="repair")
    conn.commit()

    examples = dsb.harvest(path)
    assert [e["run_id"] for e in examples] == ["r1"]


def test_build_writes_chat_jsonl_with_compact_assistant(db, tmp_path):
    path, conn = db
    for i in range(10):
        _seed_run(conn, f"r{i}", f"gif del kanji número {i}")
    conn.commit()

    out = tmp_path / "dataset"
    stats = dsb.build(path, out)
    assert stats["unique"] == 10
    assert stats["train"] + stats["valid"] == 10
    assert stats["valid"] >= 1

    first = json.loads((out / "train.jsonl").read_text().splitlines()[0])
    roles = [m["role"] for m in first["messages"]]
    assert roles == ["system", "user", "assistant"]
    compact = json.loads(first["messages"][2]["content"])
    assert set(compact) == {"f", "g", "a"}
    assert compact["a"][0] == ["w", 1000]
    # nombres limpios derivados del pedido (no manglados)
    assert compact["f"].startswith("acciones-") and compact["f"].endswith(".json")
    assert compact["g"].endswith(".gif")
    assert compact["f"].isascii() and compact["g"].isascii()
    assert "Inventario real" in first["messages"][1]["content"]


def test_duplicates_deduped(db, tmp_path):
    path, conn = db
    _seed_run(conn, "r1", "gif del kanji 水")
    _seed_run(conn, "r2", "gif del kanji 水")  # mismo pedido y mismo plan
    conn.commit()

    stats = dsb.build(path, tmp_path / "ds")
    assert stats["total"] == 2
    assert stats["unique"] == 1
