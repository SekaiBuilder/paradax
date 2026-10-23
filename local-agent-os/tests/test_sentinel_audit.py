from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from agent_os.sandbox.sentinel_audit import SentinelAudit


def _seed_db(db_path: Path, run_id: str, events: list[dict]) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, agent TEXT, status TEXT, request TEXT,
            model TEXT, output_json TEXT, error TEXT, created_at TEXT, updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS run_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT, kind TEXT, payload_json TEXT, created_at TEXT
        )
    """)
    conn.execute(
        "INSERT OR IGNORE INTO runs VALUES (?, 'test', 'running', 'req', NULL, '{}', NULL, '2025-01-01', '2025-01-01')",
        (run_id,),
    )
    for ev in events:
        conn.execute(
            "INSERT INTO run_events (run_id, kind, payload_json, created_at) VALUES (?, ?, ?, '2025-01-01')",
            (run_id, ev["kind"], json.dumps(ev["payload"])),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def patched_db(tmp_path, monkeypatch):
    db_path = tmp_path / "agent_os.sqlite3"
    import agent_os.db as db_mod
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "ensure_dirs", lambda: None)
    return db_path


def test_clean_run(patched_db):
    run_id = "run-clean"
    _seed_db(patched_db, run_id, [
        {"kind": "sandbox_tool", "payload": {"ok": True, "tool": "code_read_file", "agent_id": "a"}},
        {"kind": "sandbox_tool", "payload": {"ok": True, "tool": "code_read_file", "agent_id": "a"}},
    ])
    report = SentinelAudit(threshold=3).audit(run_id)
    assert report.verdict == "clean"
    assert report.blocked_calls == 0
    assert report.tool_calls == 2


def test_violations_below_threshold(patched_db):
    run_id = "run-violations"
    _seed_db(patched_db, run_id, [
        {"kind": "sandbox_tool", "payload": {"ok": False, "tool": "bad_tool", "agent_id": "a", "blocked_by": "broker"}},
        {"kind": "sandbox_tool", "payload": {"ok": False, "tool": "bad_tool", "agent_id": "a", "blocked_by": "broker"}},
    ])
    report = SentinelAudit(threshold=3).audit(run_id)
    assert report.verdict == "violations"
    assert report.blocked_calls == 2


def test_rollback_triggered(patched_db, monkeypatch):
    run_id = "run-rollback"
    _seed_db(patched_db, run_id, [
        {"kind": "sandbox_tool", "payload": {"ok": False, "tool": "x", "agent_id": "a", "blocked_by": "broker"}},
        {"kind": "sandbox_tool", "payload": {"ok": False, "tool": "x", "agent_id": "a", "blocked_by": "broker"}},
        {"kind": "sandbox_tool", "payload": {"ok": False, "tool": "x", "agent_id": "a", "blocked_by": "broker"}},
        {"kind": "sandbox_tool", "payload": {"ok": False, "tool": "x", "agent_id": "a", "blocked_by": "broker"}},
    ])
    rolled_back_to = []

    def fake_undo(sha: str, root=None):
        rolled_back_to.append(sha)
        return {"ok": True, "sha": sha, "error": ""}

    monkeypatch.setattr("agent_os.sandbox.sentinel_audit.undo_to", fake_undo)

    report = SentinelAudit(threshold=3).audit(run_id, pre_sha="abc123")
    assert report.verdict == "rollback"
    assert rolled_back_to == ["abc123"]
    assert report.rollback_sha == "abc123"
