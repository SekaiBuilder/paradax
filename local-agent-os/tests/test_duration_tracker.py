from __future__ import annotations

import pytest

from agent_os.automation.duration_tracker import BUFFER_FACTOR, DurationTracker


@pytest.fixture
def tracker(tmp_path, monkeypatch):
    import agent_os.automation.duration_tracker as mod
    monkeypatch.setattr(mod, "DURATIONS_FILE", tmp_path / "durations.json")
    return DurationTracker()


def test_no_history_uses_default(tracker):
    est = tracker.estimated_seconds("proj-1", "media", default_minutes=60)
    assert est == pytest.approx(60 * 60 * BUFFER_FACTOR)


def test_records_and_averages(tracker):
    tracker.record("proj-1", "media", 3600.0)
    tracker.record("proj-1", "media", 3000.0)
    avg = (3600 + 3000) / 2
    assert tracker.estimated_seconds("proj-1", "media") == pytest.approx(avg * BUFFER_FACTOR)


def test_max_history_capped(tracker):
    for i in range(15):
        tracker.record("proj-1", "code", float(i * 60))
    hist = tracker.history("proj-1", "code")
    assert len(hist) == 10  # MAX_HISTORY


def test_different_projects_isolated(tracker):
    tracker.record("proj-a", "media", 120.0)
    tracker.record("proj-b", "media", 600.0)
    assert tracker.history("proj-a", "media") == [120.0]
    assert tracker.history("proj-b", "media") == [600.0]


def test_summary_with_data(tracker):
    tracker.record("proj-1", "media", 3600.0)
    s = tracker.summary("proj-1", "media")
    assert s["runs"] == 1
    assert s["avg_minutes"] == pytest.approx(60.0)
    assert s["estimated_minutes"] == pytest.approx(60 * BUFFER_FACTOR)


def test_summary_no_data(tracker):
    s = tracker.summary("proj-x", "code")
    assert s["runs"] == 0
    assert s["avg_minutes"] is None
