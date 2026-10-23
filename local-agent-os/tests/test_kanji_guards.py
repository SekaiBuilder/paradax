from __future__ import annotations

import pytest

import agent_os.core.agent as core_agent
from agent_os.agents.action_planner import ActionPlannerAgent, _kanji_table_guards

PREFIX = [
    {"accion": "esperar", "ms": 1000},
    {"accion": "click", "selector": ".ck-accept-btn"},
    {"accion": "esperar", "ms": 2500},
    {"accion": "click", "selector": "#tut-x"},
    {"accion": "esperar", "ms": 500},
    {"accion": "marcar"},
]

BACKUP = "td.kanji-clickable >> nth=0"


def test_table_start_removed_when_cell_clicked():
    actions = PREFIX + [
        {"accion": "click", "selector": "#btn-kanji"},
        {"accion": "esperar", "ms": 1200},
        {"accion": "click", "selector": "[data-table-start='kanji-table-panel']"},
        {"accion": "esperar", "ms": 1500},
        {"accion": "click", "selector": 'td.kanji-clickable:has-text("水") >> nth=0'},
        {"accion": "esperar", "ms": 2000},
    ]
    guarded, discarded = _kanji_table_guards(actions)
    selectors = [a.get("selector") for a in guarded]
    assert discarded == 1
    assert "[data-table-start='kanji-table-panel']" not in selectors


def test_flashcards_removed_when_cell_clicked():
    actions = [
        {"accion": "click", "selector": "#btn-kanji"},
        {"accion": "click", "selector": "#btn-kanji-flashcards"},
        {"accion": "click", "selector": 'td.kanji-clickable:has-text("古") >> nth=0'},
    ]
    guarded, discarded = _kanji_table_guards(actions)
    assert discarded == 1
    assert all("flashcards" not in (a.get("selector") or "") for a in guarded)


def test_backup_click_inserted_after_has_text():
    actions = [
        {"accion": "click", "selector": "#btn-kanji"},
        {"accion": "click", "selector": 'td.kanji-clickable:has-text("水") >> nth=0'},
        {"accion": "esperar", "ms": 2000},
    ]
    guarded, _ = _kanji_table_guards(actions)
    selectors = [a.get("selector") for a in guarded]
    i = selectors.index('td.kanji-clickable:has-text("水") >> nth=0')
    assert selectors[i + 1] == BACKUP


def test_backup_not_duplicated_if_model_included_it():
    actions = [
        {"accion": "click", "selector": 'td.kanji-clickable:has-text("水") >> nth=0'},
        {"accion": "click", "selector": BACKUP},
    ]
    guarded, _ = _kanji_table_guards(actions)
    assert [a.get("selector") for a in guarded].count(BACKUP) == 1


def test_flashcards_kept_when_no_cell_click():
    actions = [
        {"accion": "click", "selector": "#btn-kanji"},
        {"accion": "click", "selector": "#btn-kanji-flashcards"},
        {"accion": "clickxy", "x": 270, "y": 450},
    ]
    guarded, discarded = _kanji_table_guards(actions)
    assert discarded == 0
    assert len(guarded) == 3


@pytest.mark.asyncio
async def test_guards_applied_end_to_end(monkeypatch, planner_ctx):
    bad_plan = {
        "reasoning_summary": "demo",
        "actions_file_name": "acciones-kanji.json",
        "gif_output_name": "kanji.gif",
        "actions": PREFIX + [
            {"accion": "click", "selector": "#btn-kanji"},
            {"accion": "esperar", "ms": 1200},
            {"accion": "click", "selector": "[data-table-start='kanji-table-panel']"},
            {"accion": "click", "selector": 'td.kanji-clickable:has-text("水") >> nth=0'},
            {"accion": "esperar", "ms": 2000},
        ],
    }

    async def fake_chat(model, system, user):
        return bad_plan

    monkeypatch.setattr(core_agent, "chat_json", fake_chat)
    plan = await ActionPlannerAgent().run(planner_ctx)
    selectors = [getattr(a, "selector", None) for a in plan.actions]
    assert "[data-table-start='kanji-table-panel']" not in selectors
    assert BACKUP in selectors
    assert plan.discarded_actions == 1
