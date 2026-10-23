from __future__ import annotations

from datetime import datetime

import pytest

from agent_os.automation.duration_tracker import DurationTracker
from agent_os.automation.smart_scheduler import (
    compute_start_time,
    create_schedule,
    delete_schedule,
    should_fire,
)


@pytest.fixture
def patched_files(tmp_path, monkeypatch):
    import agent_os.automation.smart_scheduler as mod
    import agent_os.automation.duration_tracker as dur_mod
    monkeypatch.setattr(mod, "SMART_SCHEDULES_FILE", tmp_path / "smart_schedules.json")
    monkeypatch.setattr(dur_mod, "DURATIONS_FILE", tmp_path / "durations.json")
    return tmp_path


# ── compute_start_time ────────────────────────────────────────────────────────

def test_compute_start_time_exact():
    # 3h00 deadline, 5400s estimado (90min) → 01:30
    result = compute_start_time("03:00", 5400.0)
    assert result == "01:30"


def test_compute_start_time_with_buffer():
    # 5400s * 1.2 (buffer ya aplicado por DurationTracker) → el caller pasa ya con buffer
    result = compute_start_time("06:00", 3600.0)
    assert result == "05:00"


def test_compute_start_time_midnight_cross():
    # deadline 01:00, estimado 3h → 22:00 del día anterior (se representa como 22:00)
    result = compute_start_time("01:00", 3 * 3600.0)
    assert result == "22:00"


# ── should_fire ───────────────────────────────────────────────────────────────

def test_should_fire_at_correct_time(patched_files):
    tracker = DurationTracker()
    # Sin historial → usa default 60min * 1.2 = 72min
    s = {
        "id": "s1", "project_id": "p1", "enabled": True,
        "deadline_time": "03:00", "days_of_month": [15],
        "task_kind": "media", "default_duration_minutes": 60,
        "last_fired": "",
    }
    # start_time = 03:00 - 72min = 01:48
    start = compute_start_time("03:00", tracker.estimated_seconds("p1", "media", 60))
    h, m = map(int, start.split(":"))
    now = datetime(2025, 1, 15, h, m)
    assert should_fire(s, now, tracker)


def test_should_not_fire_disabled(patched_files):
    tracker = DurationTracker()
    s = {
        "id": "s1", "project_id": "p1", "enabled": False,
        "deadline_time": "03:00", "days_of_month": [15],
        "task_kind": "media", "default_duration_minutes": 60,
        "last_fired": "",
    }
    now = datetime(2025, 1, 15, 1, 48)
    assert not should_fire(s, now, tracker)


def test_should_not_fire_wrong_day(patched_files):
    tracker = DurationTracker()
    s = {
        "id": "s1", "project_id": "p1", "enabled": True,
        "deadline_time": "03:00", "days_of_month": [20],
        "task_kind": "media", "default_duration_minutes": 60,
        "last_fired": "",
    }
    now = datetime(2025, 1, 15, 1, 48)
    assert not should_fire(s, now, tracker)


def test_should_not_fire_already_fired(patched_files):
    tracker = DurationTracker()
    start = compute_start_time("03:00", tracker.estimated_seconds("p1", "media", 60))
    h, m = map(int, start.split(":"))
    stamp = f"2025-01-15 {h:02d}:{m:02d}"
    s = {
        "id": "s1", "project_id": "p1", "enabled": True,
        "deadline_time": "03:00", "days_of_month": [15],
        "task_kind": "media", "default_duration_minutes": 60,
        "last_fired": stamp,
    }
    now = datetime(2025, 1, 15, h, m)
    assert not should_fire(s, now, tracker)


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_create_and_delete(patched_files):
    s = create_schedule("proj-1", "03:00", [1, 15], task_kind="media")
    assert s["deadline_time"] == "03:00"
    assert s["task_kind"] == "media"
    removed = delete_schedule(s["id"])
    assert removed
