from __future__ import annotations

import uuid

import pytest

from agent_os import db, project_runner as pr
from agent_os.factory.loader import DYNAMIC, make_agent
from agent_os.factory.project import Project
from agent_os.factory.spec import AgentSpec

IMPL_SPEC = AgentSpec(
    id="impl_test_escal", name="Implementador test", description="edita código",
    reads=["feature_request"], writes="implementation_report",
    output_schema={"summary": "str", "changed_files": "list[str]", "tests_run": "list[str]", "status": "str"},
    tools=["code_replace"], uses_tools=True,
    prompt="Edita código y reporta.",
)


@pytest.fixture
def _registered_blocked_agent(monkeypatch):
    agent = make_agent(IMPL_SPEC)

    async def blocked_exec(ctx):
        return agent.contract.output_model(summary="no pude", changed_files=[], tests_run=[], status="blocked")

    monkeypatch.setattr(agent, "execute", blocked_exec)
    DYNAMIC._agents[IMPL_SPEC.id] = agent
    yield agent
    DYNAMIC._agents.pop(IMPL_SPEC.id, None)


@pytest.mark.asyncio
async def test_blocked_executor_escalates_to_claude(monkeypatch, _registered_blocked_agent):
    async def fake_escalate(task, technical_spec):
        return {"summary": "Claude Code editó styles.css", "changed_files": ["local-agent-os/static/styles.css"],
                "tests_run": ["pytest: 1 passed"], "status": "done", "executor": "claude_code"}

    monkeypatch.setattr(pr, "_escalate_executor", fake_escalate)

    run_id = f"test-{uuid.uuid4().hex[:6]}"
    db.init_db()
    db.create_run(run_id, "test", "haz X", "m")
    project = Project(id="p-escal", name="P", goal="g", agents=[IMPL_SPEC.id])

    result = await pr._contract_run(project, "m", run_id, {"feature_request": "agrega un comentario en app.js"})

    out = result["outputs"][IMPL_SPEC.id]
    assert out["status"] == "done"                       # el bloqueo se resolvió
    assert out["changed_files"] == ["local-agent-os/static/styles.css"]
    assert out["escalated_to"] == "claude_code"
    assert pr.result_status(result) == "completed"


@pytest.mark.asyncio
async def test_no_escalation_when_disabled(monkeypatch, _registered_blocked_agent):
    monkeypatch.setattr(pr, "ENABLE_CLAUDE_ESCALATION", False)
    called = {"n": 0}

    async def fake_escalate(task, spec):
        called["n"] += 1
        return {}

    monkeypatch.setattr(pr, "_escalate_executor", fake_escalate)
    run_id = f"test-{uuid.uuid4().hex[:6]}"
    db.init_db(); db.create_run(run_id, "test", "x", "m")
    project = Project(id="p-escal2", name="P", goal="g", agents=[IMPL_SPEC.id])

    result = await pr._contract_run(project, "m", run_id, {"feature_request": "x"})
    assert called["n"] == 0
    assert result["outputs"][IMPL_SPEC.id]["status"] == "blocked"
