from __future__ import annotations

import pytest

import agent_os.core.models as models_mod
import agent_os.db as db_mod


@pytest.fixture(autouse=True)
def isolate_models(monkeypatch, tmp_path):
    """Aísla los tests del data/models.json real: por defecto, modo maestro
    (sin alumno promocionado). Los tests que quieran un alumno parchean
    MODELS_FILE explícitamente después — ese parche gana dentro del test."""
    monkeypatch.setattr(models_mod, "MODELS_FILE", tmp_path / "no_models.json")


@pytest.fixture(autouse=True)
def isolate_db(monkeypatch, tmp_path):
    """Aísla los tests del data/agent_os.sqlite3 real: los tests que llaman
    db.create_run/finish_run directamente (p.ej. test_runner_escalation.py)
    escribían runs 'running' huérfanos en la DB de producción — nunca se
    marcaban terminados porque el test no pasa por el try/finally de
    project_runner.run_project. Cada test recibe su propia DB en tmp_path."""
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path / "test_agent_os.sqlite3")


@pytest.fixture(autouse=True)
def isolate_safety_repo(monkeypatch, tmp_path):
    """Las instantáneas de seguridad hacen «git add -A» y «git commit» (y deshacer, «git reset
    --hard») en PARADAX_ROOT: en un test acababan como commits reales en el repositorio de quien
    ejecuta las pruebas. Cada test recibe un repositorio vacío en tmp_path."""
    import agent_os.factory.safety as safety_mod
    repo = tmp_path / "safety-repo"
    repo.mkdir()
    monkeypatch.setattr(safety_mod, "PARADAX_ROOT", repo)


@pytest.fixture
def inventory_kana() -> dict:
    """Inventario como el que devuelve PageInspector sobre Kana Trainer."""
    return {
        "url": "https://kana.example.com",
        "fetched": True,
        "ids": ["btn-hiragana", "btn-katakana", "btn-kanji", "tut-x", "btn-hiragana-flashcards"],
        "classes": ["ck-accept-btn", "kanji-clickable", "btn-quiz-modal"],
        "data_selectors": ["[data-study-type='kanji']", "[data-quiz-mode='auto']"],
        "note": "",
    }


@pytest.fixture
def planner_ctx(inventory_kana) -> dict:
    return {
        "request": "haz un gif del kanji 水",
        "url": "https://kana.example.com",
        "project": {"name": "kana-trainer", "url": "https://kana.example.com"},
        "inventory": inventory_kana,
        "model": "test-model",
    }


@pytest.fixture
def gif_ok() -> dict:
    return {
        "path": "/tmp/demo.gif",
        "verification": {"exists": True, "path": "/tmp/demo.gif", "duration": 8.4, "size": 900_000, "ok": True},
        "failed_steps": 0,
    }


@pytest.fixture
def gif_broken() -> dict:
    return {
        "path": "/tmp/demo.gif",
        "verification": {"exists": True, "path": "/tmp/demo.gif", "duration": 1.2, "size": 40_000, "ok": True},
        "failed_steps": 2,
    }
