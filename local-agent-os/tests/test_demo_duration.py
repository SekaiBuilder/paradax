from __future__ import annotations

import pytest

import agent_os.core.agent as core_agent
from agent_os.agents.action_planner import (
    MIN_DEMO_MS,
    ActionPlannerAgent,
    _ensure_min_demo,
    extract_kanji,
)


def _demo_ms(actions):
    start = max(i for i, a in enumerate(actions) if a.get("accion") == "marcar") + 1
    return sum(int(a.get("ms") or 0) for a in actions[start:] if a.get("accion") == "esperar")


def test_short_demo_gets_extended():
    actions = [
        {"accion": "marcar"},
        {"accion": "click", "selector": "#btn-kanji"},
        {"accion": "esperar", "ms": 1000},
    ]
    _ensure_min_demo(actions)
    assert _demo_ms(actions) >= MIN_DEMO_MS


def test_long_demo_untouched():
    actions = [
        {"accion": "marcar"},
        {"accion": "click", "selector": "#btn-kanji"},
        {"accion": "esperar", "ms": 6000},
    ]
    before = [dict(a) for a in actions]
    _ensure_min_demo(actions)
    assert actions == before


def test_extension_respects_wait_clamp():
    actions = [
        {"accion": "marcar"},
        {"accion": "esperar", "ms": 200},
        {"accion": "click", "selector": "#btn-kanji"},
        {"accion": "esperar", "ms": 7900},
    ]
    # total=8100 ya supera el mínimo: no toca nada
    before = [dict(a) for a in actions]
    _ensure_min_demo(actions)
    assert actions == before

    short = [
        {"accion": "marcar"},
        {"accion": "esperar", "ms": 7900},
    ]
    # bump excedería 8000 → añade espera nueva en rango
    _ensure_min_demo(short)
    assert short[-1]["accion"] == "esperar"
    assert 200 <= short[-1]["ms"] <= 8000


def test_plan_ending_without_wait_gets_tail():
    actions = [
        {"accion": "marcar"},
        {"accion": "click", "selector": "#btn-kanji"},
    ]
    _ensure_min_demo(actions)
    assert actions[-1]["accion"] == "esperar"
    assert actions[-1]["ms"] >= 1000


def test_extract_kanji_skips_the_word_kanji():
    assert extract_kanji("gif del 漢字 三 usando Kana Trainer") == "三"
    assert extract_kanji("muéstrame el kanji 水") == "水"
    assert extract_kanji("flashcards de hiragana") is None
    # 漢 pedido explícitamente como kanji objetivo sigue sin romper:
    assert extract_kanji("gif del 漢字 漢") == "漢"


@pytest.mark.asyncio
async def test_short_model_plan_extended_end_to_end(monkeypatch, planner_ctx):
    short_plan = {
        "reasoning_summary": "demo corta",
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
            {"accion": "esperar", "ms": 800},
        ],
    }

    async def fake_chat(model, system, user):
        return short_plan

    monkeypatch.setattr(core_agent, "chat_json", fake_chat)
    plan = await ActionPlannerAgent().run(planner_ctx)
    dumped = [a.model_dump() for a in plan.actions]
    assert _demo_ms(dumped) >= MIN_DEMO_MS