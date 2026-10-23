from __future__ import annotations

import asyncio

import pytest

from agent_os.sandbox.bus import SandboxBus
from agent_os.sandbox.protocol import ToolBlockedError, ToolRequest, ToolResponse
from agent_os.sandbox.sentinel_watch import SentinelWatch
from agent_os.sandbox.tool_broker import ToolBroker
from agent_os.factory.tool_runtime import ToolRuntime


def _make_runtime(*names: str) -> ToolRuntime:
    rt = ToolRuntime()
    for name in names:
        rt.register(name, lambda **_: f"result:{name}")
    return rt


def _make_req(tool_name: str, agent_id: str = "agent-a", run_id: str = "run-1") -> ToolRequest:
    return ToolRequest(
        request_id="req-1",
        run_id=run_id,
        agent_id=agent_id,
        tool_name=tool_name,
        args={},
    )


async def _run_watch_once(watch: SentinelWatch, req: ToolRequest) -> ToolResponse:
    """Lanza Watch, envía un request, espera respuesta y para el watch."""
    task = asyncio.create_task(watch.run())
    await watch._bus.post(req)
    resp = await req.reply_queue.get()
    await watch._bus.close()
    await asyncio.wait_for(task, timeout=2.0)
    return resp


@pytest.mark.asyncio
async def test_approved_tool():
    bus = SandboxBus()
    broker = ToolBroker.for_task("run-1", "code")
    rt = _make_runtime("code_read_file")
    watch = SentinelWatch(bus, broker, rt)

    req = _make_req("code_read_file")
    resp = await _run_watch_once(watch, req)

    assert resp.ok
    assert resp.blocked_by == ""


@pytest.mark.asyncio
async def test_blocked_by_broker():
    bus = SandboxBus()
    broker = ToolBroker.for_task("run-1", "code")  # "record_page_gif" NO está en "code"
    rt = _make_runtime("record_page_gif")
    watch = SentinelWatch(bus, broker, rt)

    req = _make_req("record_page_gif")
    resp = await _run_watch_once(watch, req)

    assert not resp.ok
    assert resp.blocked_by == "broker"


@pytest.mark.asyncio
async def test_blocked_by_contract():
    bus = SandboxBus()
    broker = ToolBroker.for_task("run-1", "code")
    rt = _make_runtime("code_read_file", "code_replace")
    # El contrato del agente solo permite code_read_file, no code_replace
    contracts = {"agent-a": frozenset({"code_read_file"})}
    watch = SentinelWatch(bus, broker, rt, agent_contracts=contracts)

    req = _make_req("code_replace")
    resp = await _run_watch_once(watch, req)

    assert not resp.ok
    assert resp.blocked_by == "contract"


@pytest.mark.asyncio
async def test_blocked_by_runtime():
    bus = SandboxBus()
    broker = ToolBroker.for_task("run-1", "code")
    rt = ToolRuntime()  # sin callables registrados
    watch = SentinelWatch(bus, broker, rt)

    req = _make_req("code_read_file")
    resp = await _run_watch_once(watch, req)

    assert not resp.ok
    assert resp.blocked_by == "runtime"


@pytest.mark.asyncio
async def test_tool_blocked_error_via_runtime(monkeypatch):
    """Verifica que ToolRuntime.call() lanza ToolBlockedError cuando sandbox activo."""
    from agent_os.factory.tool_runtime import SANDBOX_BUS_VAR, SANDBOX_RUN_ID_VAR, SANDBOX_AGENT_ID_VAR

    bus = SandboxBus()
    broker = ToolBroker.for_task("run-x", "code")
    rt_exec = _make_runtime("code_read_file")

    # Activar sandbox en contextvars
    SANDBOX_BUS_VAR.set(bus)
    SANDBOX_RUN_ID_VAR.set("run-x")
    SANDBOX_AGENT_ID_VAR.set("agent-z")

    watch = SentinelWatch(bus, broker, rt_exec)
    watch_task = asyncio.create_task(watch.run())

    # Crear un ToolRuntime con sandbox activo — llamada bloqueada por broker
    rt_blocker = _make_runtime("record_page_gif")
    with pytest.raises(ToolBlockedError):
        await rt_blocker.call("record_page_gif", {})

    await bus.close()
    await asyncio.wait_for(watch_task, timeout=2.0)

    # Limpiar contextvars
    SANDBOX_BUS_VAR.set(None)
