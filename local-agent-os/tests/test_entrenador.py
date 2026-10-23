from __future__ import annotations

from agent_os.factory.entrenador import Entrenador


def _ent(tmp_path):
    return Entrenador(models_file=tmp_path / "models.json")


def test_status_defaults_to_master(tmp_path):
    st = _ent(tmp_path).status("action_planner", fallback="qwen3-coder:30b")
    assert st["specialized"] is False
    assert st["active_model"] == "qwen3-coder:30b"
    assert st["engine"] == "maestro"


def test_promote_then_status_specialized(tmp_path):
    ent = _ent(tmp_path)
    ent.promote("action_planner", "agent-os/action-planner:v1")
    st = ent.status("action_planner")
    assert st["specialized"] is True
    assert st["active_model"] == "agent-os/action-planner:v1"
    assert st["engine"] == "alumno propio"


def test_demote(tmp_path):
    ent = _ent(tmp_path)
    ent.promote("x", "agent-os/x:v1")
    ent.demote("x")
    assert ent.status("x")["specialized"] is False


def test_roster_explicit_ids(tmp_path):
    ent = _ent(tmp_path)
    ent.promote("a", "agent-os/a:v1")
    roster = ent.roster(["a", "b"])
    by_id = {r["agent_id"]: r for r in roster}
    assert by_id["a"]["specialized"] is True
    assert by_id["b"]["specialized"] is False


def test_training_plan_has_four_steps(tmp_path):
    plan = _ent(tmp_path).training_plan("action_planner", "v2")
    assert [s["step"] for s in plan] == ["generar", "cosechar", "entrenar", "evaluar"]
    assert "v2" in plan[2]["cmd"]
