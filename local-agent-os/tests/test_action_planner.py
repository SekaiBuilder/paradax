from __future__ import annotations

import pytest

import agent_os.core.agent as core_agent
from agent_os.agents.action_planner import ActionPlannerAgent

VALID_PLAN = {
    "reasoning_summary": "demo kanji",
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


def _patch_model(monkeypatch, responses: list[dict | Exception]):
    """chat_json devuelve cada respuesta en orden; Exception → raise."""
    calls = {"n": 0}

    async def fake_chat(model, system, user):
        i = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        r = responses[i]
        if isinstance(r, Exception):
            raise r
        return r

    monkeypatch.setattr(core_agent, "chat_json", fake_chat)
    return calls


@pytest.mark.asyncio
async def test_valid_plan_passes(monkeypatch, planner_ctx):
    _patch_model(monkeypatch, [VALID_PLAN])
    plan = await ActionPlannerAgent().run(planner_ctx)
    assert plan.plan_source == "model"
    assert plan.gif_output_name == "kanji.gif"
    assert any(a.accion == "marcar" for a in plan.actions)


@pytest.mark.asyncio
async def test_plan_without_marcar_gets_popup_prefix(monkeypatch, planner_ctx):
    bare = dict(VALID_PLAN, actions=[{"accion": "click", "selector": "#btn-kanji"}])
    _patch_model(monkeypatch, [bare])
    plan = await ActionPlannerAgent().run(planner_ctx)
    kinds = [a.accion for a in plan.actions]
    assert kinds[:6] == ["esperar", "click", "esperar", "click", "esperar", "marcar"]


@pytest.mark.asyncio
async def test_invented_selector_rejected_then_retried(monkeypatch, planner_ctx):
    invented = dict(
        VALID_PLAN,
        actions=VALID_PLAN["actions"] + [{"accion": "click", "selector": "#boton-inventado-xyz"}],
    )
    calls = _patch_model(monkeypatch, [invented, VALID_PLAN])
    plan = await ActionPlannerAgent().run(planner_ctx)
    assert calls["n"] == 2, "debe reintentar tras el rechazo semántico"
    assert plan.plan_source == "model_retry_1"


@pytest.mark.asyncio
async def test_model_error_falls_back_to_safe_plan(monkeypatch, planner_ctx):
    _patch_model(monkeypatch, [RuntimeError("ollama caído")])
    plan = await ActionPlannerAgent().run(planner_ctx)
    assert plan.plan_source.startswith("fallback:")
    # El pedido menciona 水 → el fallback abre la sección kanji
    assert any(getattr(a, "selector", "") == "#btn-kanji" for a in plan.actions)
    assert plan.gif_output_name == "kanji-6c34.gif"


@pytest.mark.asyncio
async def test_garbage_actions_dropped_and_waits_clamped(monkeypatch, planner_ctx):
    messy = dict(
        VALID_PLAN,
        actions=VALID_PLAN["actions"]
        + [
            {"accion": "inventada", "selector": "#x"},
            "no-soy-un-dict",
            {"accion": "esperar", "ms": 60000},
        ],
    )
    _patch_model(monkeypatch, [messy])
    plan = await ActionPlannerAgent().run(planner_ctx)
    assert plan.discarded_actions == 2
    assert all(a.accion != "inventada" for a in plan.actions)
    waits = [a.model_dump().get("ms") for a in plan.actions if a.accion == "esperar"]
    assert max(waits) <= 8000


def test_repair_plan_has_unique_names():
    planner = ActionPlannerAgent()
    plan = planner.repair_plan("gif del kanji 水", "run-abc123")
    assert plan.plan_source == "repair"
    assert "run-abc123" in plan.actions_file_name
    assert "run-abc123" in plan.gif_output_name
    assert plan.gif_output_name.endswith(".gif")
