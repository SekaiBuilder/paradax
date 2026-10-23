from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

import agent_os.db as db
from agent_os.core.agent import Agent, AgentError
from agent_os.core.contract import AgentContract
from agent_os import project_runner


class SpecOut(BaseModel):
    summary: str


class ReportOut(BaseModel):
    status: str


class DummyAgent(Agent):
    def __init__(self, agent_id, reads, writes, output_model, payload):
        self.contract = AgentContract(
            id=agent_id,
            name=agent_id,
            description=agent_id,
            reads=tuple(reads),
            writes=writes,
            output_model=output_model,
        )
        self.payload = payload

    async def execute(self, ctx):
        return self.payload


class FailingAgent(DummyAgent):
    async def execute(self, ctx):
        raise AgentError(self.contract.id, "fallo intencional")


class FakeRegistry:
    def __init__(self, agents):
        self.agents = agents

    def get(self, agent_id):
        return self.agents.get(agent_id)


def _project(**over):
    data = dict(
        id="demo",
        name="Demo",
        goal="Mejorar Demo",
        description="Proyecto de prueba",
        agents=["analista", "implementador"],
        inputs={},
    )
    data.update(over)
    return SimpleNamespace(**data)


@pytest.fixture
def registry(monkeypatch):
    agents = {
        "analista": DummyAgent(
            "analista",
            ["feature_request", "workspace_root"],
            "technical_spec",
            SpecOut,
            {"summary": "plan"},
        ),
        "implementador": DummyAgent(
            "implementador",
            ["feature_request", "technical_spec", "project_context"],
            "implementation_report",
            ReportOut,
            {"status": "done"},
        ),
    }
    reg = FakeRegistry(agents)
    monkeypatch.setattr(project_runner, "DYNAMIC", reg)
    return reg


def test_task_inputs_fill_common_keys(registry):
    p = _project()
    seed = project_runner.task_inputs(p, "agrega dark mode")

    assert seed["feature_request"] == "agrega dark mode"
    # La raíz de Paradax, se llame como se llame la carpeta del clon.
    assert seed["workspace_root"] == str(project_runner.PARADAX_ROOT)
    assert "workspace_map" in seed
    assert "Proyecto: Demo" in seed["project_context"]
    assert "technical_spec" not in seed  # lo produce el analista


def test_workspace_map_uses_real_static_layout(tmp_path, monkeypatch):
    root = tmp_path / "paradax"
    static = root / "local-agent-os" / "static"
    static.mkdir(parents=True)
    (static / "index.html").write_text("<main></main>", encoding="utf-8")
    (static / "app.js").write_text("console.log('ok')", encoding="utf-8")
    (static / "styles.css").write_text(".btn { color: white; }", encoding="utf-8")
    monkeypatch.setattr(project_runner, "PARADAX_ROOT", root)

    workspace_map = project_runner._workspace_map()

    assert "src_dir_exists: no" in workspace_map
    assert "local-agent-os/static/styles.css" in workspace_map
    assert "no asumas rutas src/" in workspace_map


def test_compute_plan_schedules_chain_with_task_seed(registry):
    p = _project()
    seed = project_runner.task_inputs(p, "agrega dark mode")
    plan = project_runner.compute_plan(p, set(seed))

    assert plan["order"] == ["analista", "implementador"]
    assert plan["blocked"] == []


@pytest.mark.asyncio
async def test_run_project_returns_outputs_and_run_id(registry, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "runs.sqlite3")
    p = _project()
    seed = project_runner.task_inputs(p, "agrega dark mode")

    result = await project_runner.run_project(p, model="m", request="agrega dark mode", seed_override=seed)

    assert result["run_id"].startswith("proj-demo-")
    assert result["status"] == "completed"
    assert result["ran"] == ["analista", "implementador"]
    assert result["errors"] == []
    assert result["outputs"]["implementador"] == {"status": "done"}


@pytest.mark.asyncio
async def test_run_project_without_seed_uses_project_goal(registry, tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "runs.sqlite3")
    p = _project(goal="agrega dark mode")

    result = await project_runner.run_project(p, model="m")

    assert result["status"] == "completed"
    assert result["ran"] == ["analista", "implementador"]
    assert result["blocked"] == []


def test_result_status_reflects_inner_blocked_and_failed_outputs():
    assert project_runner.result_status({
        "ran": ["implementador"],
        "blocked": [],
        "errors": [],
        "skipped": [],
        "outputs": {"implementador": {"status": "blocked", "changed_files": []}},
    }) == "blocked"

    assert project_runner.result_status({
        "ran": ["verificador"],
        "blocked": [],
        "errors": [],
        "skipped": [],
        "outputs": {"verificador": {"ok": False}},
    }) == "failed"


@pytest.mark.asyncio
async def test_run_project_skips_dependents_when_upstream_fails(tmp_path, monkeypatch):
    agents = {
        "analista": FailingAgent(
            "analista",
            ["feature_request"],
            "technical_spec",
            SpecOut,
            {"summary": "unused"},
        ),
        "implementador": DummyAgent(
            "implementador",
            ["feature_request", "technical_spec"],
            "implementation_report",
            ReportOut,
            {"status": "done"},
        ),
    }
    monkeypatch.setattr(project_runner, "DYNAMIC", FakeRegistry(agents))
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "runs.sqlite3")
    p = _project(agents=["analista", "implementador"])
    seed = project_runner.task_inputs(p, "agrega dark mode")

    result = await project_runner.run_project(p, model="m", request="agrega dark mode", seed_override=seed)

    assert result["ran"] == []
    assert result["errors"][0]["agent"] == "analista"
    assert result["skipped"] == [{"agent": "implementador", "missing": ["technical_spec"]}]
