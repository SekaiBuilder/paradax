from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import DATA_DIR, ensure_dirs

DB_PATH = DATA_DIR / "agent_os.sqlite3"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    # `with sqlite3.connect(...)` solo confirma la transacción; NO cierra la
    # conexión, y cada llamada abría una nueva → fuga de descriptores.
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                agent TEXT NOT NULL,
                status TEXT NOT NULL,
                request TEXT NOT NULL,
                model TEXT,
                output_json TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS run_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES runs(id)
            )
            """
        )


def create_run(run_id: str, agent: str, request: str, model: str | None) -> None:
    now = utc_now()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO runs (id, agent, status, request, model, created_at, updated_at)
            VALUES (?, ?, 'running', ?, ?, ?, ?)
            """,
            (run_id, agent, request, model, now, now),
        )


def add_event(run_id: str, kind: str, payload: dict[str, Any]) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO run_events (run_id, kind, payload_json, created_at) VALUES (?, ?, ?, ?)",
            (run_id, kind, json.dumps(payload, ensure_ascii=False), utc_now()),
        )


def finish_run(
    run_id: str,
    status: str,
    output: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE runs
            SET status = ?, output_json = ?, error = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                json.dumps(output or {}, ensure_ascii=False),
                error,
                utc_now(),
                run_id,
            ),
        )


def list_runs(limit: int = 50) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_run(row) for row in rows]


def get_run(run_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        events = conn.execute(
            "SELECT kind, payload_json, created_at FROM run_events WHERE run_id = ? ORDER BY id ASC",
            (run_id,),
        ).fetchall()
    run = _row_to_run(row)
    run["events"] = [
        {
            "kind": ev["kind"],
            "payload": json.loads(ev["payload_json"]),
            "created_at": ev["created_at"],
        }
        for ev in events
    ]
    return run


def _row_to_run(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["output"] = json.loads(data.pop("output_json") or "{}")
    return data
