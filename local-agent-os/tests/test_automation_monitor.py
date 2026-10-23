from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from agent_os.automation.monitor import AutomationMonitor, CHECK_INTERVAL_SECONDS


def _seed_run(db_path: Path, run_id: str, status: str = "running") -> None:
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
        "INSERT OR REPLACE INTO runs VALUES (?, 'test', ?, 'req', NULL, '{}', NULL, '2025-01-01', '2025-01-01')",
        (run_id, status),
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


@pytest.mark.asyncio
async def test_monitor_stops_when_run_finishes(patched_db):
    _seed_run(patched_db, "run-done", status="completed")
    monitor = AutomationMonitor("run-done", "03:00")
    # El monitor debe detectar que el run terminó en el primer check y parar
    monkeypatch_interval = 0  # sin espera en el test
    import agent_os.automation.monitor as mon_mod
    original = mon_mod.CHECK_INTERVAL_SECONDS

    # Parchear el sleep para que no espere
    async def fast_sleep(_):
        pass

    original_sleep = asyncio.sleep
    asyncio.sleep = fast_sleep
    try:
        # watch() comprueba después del primer sleep — ya está completado
        await asyncio.wait_for(monitor.watch(), timeout=2.0)
    except asyncio.TimeoutError:
        pytest.fail("El monitor no se detuvo al detectar run completado")
    finally:
        asyncio.sleep = original_sleep


@pytest.mark.asyncio
async def test_monitor_emits_at_risk_when_deadline_passed(patched_db, monkeypatch):
    from datetime import datetime
    _seed_run(patched_db, "run-late", status="running")

    events_published = []

    import agent_os.automation.monitor as mon_mod
    class FakeBUS:
        @staticmethod
        def publish(kind, payload):
            events_published.append((kind, payload))
    monkeypatch.setattr(mon_mod, "BUS", FakeBUS)

    # Deadline en el pasado → al verificar, now > deadline → at_risk
    monitor = AutomationMonitor("run-late", "00:00", schedule_id="sched-1")
    monitor._alerted = False

    # Llamar _check directamente con mocked datetime — deadline "00:00" en el pasado
    # Para el test, simplemente llamamos _check y verificamos la alerta
    # (forzamos deadline en el pasado usando una hora fija)
    from unittest.mock import patch
    from datetime import datetime as _dt
    fake_now = _dt(2025, 1, 15, 4, 0)  # 4am, deadline fue 00:00 → at_risk
    with patch("agent_os.automation.monitor.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.side_effect = lambda *a, **kw: _dt(*a, **kw)
        finished = await monitor._check()

    assert not finished  # el run sigue activo
    assert monitor._alerted
    assert any(kind == "automation_at_risk" for kind, _ in events_published)
