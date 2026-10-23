from __future__ import annotations

import json

import pytest

import agent_os.core.agent as core_agent
import agent_os.core.models as models_mod
from agent_os.agents.action_planner import ActionPlannerAgent
from agent_os.core.models import resolve_model

# Wire compacto como lo emitiría el alumno fine-tuneado.
STUDENT_WIRE = {
    "f": "acciones-kanji-6c34.json",
    "g": "kanji-6c34.gif",
    "a": [
        ["w", 1000], ["c", ".ck-accept-btn"], ["w", 2500], ["c", "#tut-x"],
        ["w", 500], ["m"], ["c", "#btn-kanji"], ["w", 1200],
        ["c", 'td.kanji-clickable:has-text("水") >> nth=0'], ["w", 2000],
    ],
}


def _models_file(tmp_path, monkeypatch, mapping):
    path = tmp_path / "models.json"
    path.write_text(json.dumps(mapping), encoding="utf-8")
    monkeypatch.setattr(models_mod, "MODELS_FILE", path)
    return path


# ── resolve_model ─────────────────────────────────────────────────────────────

def test_resolve_falls_back_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(models_mod, "MODELS_FILE", tmp_path / "missing.json")
    model, is_student = resolve_model("action_planner", "qwen3-coder:30b")
    assert model == "qwen3-coder:30b" and is_student is False


def test_resolve_returns_promoted_student(tmp_path, monkeypatch):
    _models_file(tmp_path, monkeypatch, {"action_planner": "agent-os/action-planner:v1"})
    model, is_student = resolve_model("action_planner", "qwen3-coder:30b")
    assert model == "agent-os/action-planner:v1" and is_student is True


def test_resolve_corrupt_file_falls_back(tmp_path, monkeypatch):
    path = tmp_path / "models.json"
    path.write_text("{ broken json", encoding="utf-8")
    monkeypatch.setattr(models_mod, "MODELS_FILE", path)
    model, is_student = resolve_model("action_planner", "master")
    assert model == "master" and is_student is False


# ── ActionPlanner en modo alumno ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_student_wire_decoded_and_guarded(tmp_path, monkeypatch, planner_ctx):
    _models_file(tmp_path, monkeypatch, {"action_planner": "agent-os/action-planner:v1"})
    captured = {}

    async def fake_chat(model, system, user):
        captured["model"] = model
        captured["system"] = system
        captured["user"] = user
        return STUDENT_WIRE

    monkeypatch.setattr(core_agent, "chat_json", fake_chat)
    plan = await ActionPlannerAgent().run(planner_ctx)

    # usó el modelo alumno y el prompt compacto, con el user de entrenamiento
    assert captured["model"] == "agent-os/action-planner:v1"
    assert "JSON compacto" in captured["system"]
    assert captured["user"].startswith("Pedido:")
    # wire decodificado a acciones verbosas válidas
    assert plan.plan_source.startswith("student:")
    kinds = [a.accion for a in plan.actions]
    assert "marcar" in kinds
    assert all(a.accion in {
        "esperar", "click", "escribir", "tipear", "scroll", "hover", "tecla", "clickxy", "ir", "marcar"
    } for a in plan.actions)
    # las MISMAS barreras se aplican: respaldo nth=0 tras el has-text
    selectors = [getattr(a, "selector", None) for a in plan.actions]
    assert "td.kanji-clickable >> nth=0" in selectors


@pytest.mark.asyncio
async def test_student_invalid_selector_still_rejected(tmp_path, monkeypatch, planner_ctx):
    _models_file(tmp_path, monkeypatch, {"action_planner": "agent-os/action-planner:v1"})
    bad = dict(STUDENT_WIRE, a=STUDENT_WIRE["a"] + [["c", "#inventado-zzz"], ["w", 1500]])
    calls = {"n": 0}

    async def fake_chat(model, system, user):
        calls["n"] += 1
        return bad if calls["n"] == 1 else STUDENT_WIRE

    monkeypatch.setattr(core_agent, "chat_json", fake_chat)
    plan = await ActionPlannerAgent().run(planner_ctx)
    # el selector inventado del alumno se rechaza igual que el del maestro
    assert calls["n"] == 2
    assert plan.plan_source == "student:model_retry_1"


@pytest.mark.asyncio
async def test_master_path_unchanged_without_models_file(tmp_path, monkeypatch, planner_ctx):
    monkeypatch.setattr(models_mod, "MODELS_FILE", tmp_path / "missing.json")
    verbose = {
        "reasoning_summary": "demo",
        "actions_file_name": "acciones-kanji.json",
        "gif_output_name": "kanji.gif",
        "actions": [
            {"accion": "esperar", "ms": 1000},
            {"accion": "click", "selector": ".ck-accept-btn"},
            {"accion": "marcar"},
            {"accion": "click", "selector": "#btn-kanji"},
            {"accion": "esperar", "ms": 5000},
        ],
    }
    captured = {}

    async def fake_chat(model, system, user):
        captured["model"] = model
        captured["system"] = system
        return verbose

    monkeypatch.setattr(core_agent, "chat_json", fake_chat)
    plan = await ActionPlannerAgent().run(planner_ctx)
    assert captured["model"] == "test-model"  # el maestro del ctx
    assert "JSON compacto" not in captured["system"]  # prompt verboso
    assert plan.plan_source == "model"
