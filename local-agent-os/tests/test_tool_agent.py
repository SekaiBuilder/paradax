from __future__ import annotations

import pytest

import agent_os.factory.tool_agent as ta
from agent_os.core.agent import AgentError
from agent_os.factory.loader import ConstructedAgent, make_agent
from agent_os.factory.spec import AgentSpec
from agent_os.factory.tool_agent import ToolExecutingAgent
from agent_os.factory.tool_runtime import ToolRuntime


def _spec(**over) -> AgentSpec:
    base = dict(
        id="scraper",
        name="Scraper",
        description="Lee una página y la resume.",
        reads=["url"],
        writes="research",
        output_schema={"resumen": "str"},
        tools=["http_get"],
        prompt="Eres un scraper. Usa http_get y resume.",
        uses_tools=True,
        max_tool_steps=3,
    )
    base.update(over)
    return AgentSpec(**base)


def _impl_spec(**over) -> AgentSpec:
    base = dict(
        id="implementador",
        name="Implementador",
        description="Edita código.",
        reads=["feature_request"],
        writes="implementation_report",
        output_schema={
            "summary": "str",
            "changed_files": "list[str]",
            "tests_run": "list[str]",
            "status": "str",
        },
        tools=["code_replace"],
        prompt="Edita código y reporta.",
        uses_tools=True,
        max_tool_steps=3,
    )
    base.update(over)
    return AgentSpec(**base)


def _runtime():
    rt = ToolRuntime()
    calls = []

    def http_get(url, max_chars=2000):
        calls.append(url)
        return "CONTENIDO DE LA PÁGINA"

    rt.register("http_get", http_get)
    return rt, calls


def _seq(monkeypatch, responses):
    state = {"n": 0}

    async def fake_chat(model, system, user):
        i = min(state["n"], len(responses) - 1)
        state["n"] += 1
        return responses[i]

    monkeypatch.setattr(ta, "chat_json", fake_chat)
    return state


@pytest.mark.asyncio
async def test_tool_call_then_final(monkeypatch):
    rt, calls = _runtime()
    _seq(monkeypatch, [
        {"tool": "http_get", "args": {"url": "https://a.com"}},
        {"final": {"resumen": "resumen real"}},
    ])
    agent = ToolExecutingAgent(_spec(), runtime=rt)
    out = await agent.run({"url": "https://a.com"})
    assert out.resumen == "resumen real"
    assert calls == ["https://a.com"]  # la tool se ejecutó de verdad


@pytest.mark.asyncio
async def test_final_without_wrapper(monkeypatch):
    rt, _ = _runtime()
    _seq(monkeypatch, [{"resumen": "directo"}])
    agent = ToolExecutingAgent(_spec(), runtime=rt)
    out = await agent.run({"url": "x"})
    assert out.resumen == "directo"


@pytest.mark.asyncio
async def test_disallowed_tool_blocked(monkeypatch):
    rt, calls = _runtime()
    _seq(monkeypatch, [
        {"tool": "rm", "args": {"path": "/"}},          # fuera del allow-list
        {"final": {"resumen": "ok"}},
    ])
    agent = ToolExecutingAgent(_spec(), runtime=rt)
    out = await agent.run({"url": "x"})
    assert out.resumen == "ok"
    assert calls == []  # nunca se ejecutó nada fuera de la lista


@pytest.mark.asyncio
async def test_tool_without_callable_not_executed(monkeypatch):
    # 'http_get' está permitido pero el runtime no tiene callable → no ejecuta
    rt = ToolRuntime()  # vacío
    _seq(monkeypatch, [
        {"tool": "http_get", "args": {"url": "x"}},
        {"final": {"resumen": "ok"}},
    ])
    agent = ToolExecutingAgent(_spec(), runtime=rt)
    out = await agent.run({"url": "x"})
    assert out.resumen == "ok"


@pytest.mark.asyncio
async def test_max_steps_exceeded_raises(monkeypatch):
    rt, _ = _runtime()
    _seq(monkeypatch, [{"tool": "http_get", "args": {"url": "x"}}])  # nunca termina
    agent = ToolExecutingAgent(_spec(max_tool_steps=2), runtime=rt)
    with pytest.raises(AgentError):
        await agent.run({"url": "x"})


@pytest.mark.asyncio
async def test_forces_final_after_tool_budget(monkeypatch):
    rt, calls = _runtime()
    _seq(monkeypatch, [
        {"tool": "http_get", "args": {"url": "x"}},
        {"final": {"resumen": "cerrado con evidencia"}},
    ])
    agent = ToolExecutingAgent(_spec(max_tool_steps=1), runtime=rt)
    out = await agent.run({"url": "x"})
    assert out.resumen == "cerrado con evidencia"
    assert calls == ["x"]


@pytest.mark.asyncio
async def test_done_without_write_tool_becomes_blocked(monkeypatch):
    rt = ToolRuntime()
    _seq(monkeypatch, [
        {
            "final": {
                "summary": "Cambio aplicado",
                "changed_files": [],
                "tests_run": [],
                "status": "done",
            }
        }
    ])
    agent = ToolExecutingAgent(_impl_spec(id="implementador_funcionalidades"), runtime=rt)

    out = await agent.run({"feature_request": "cambia botones"})

    assert out.status == "blocked"
    assert out.changed_files == []
    assert "No se registraron herramientas de escritura" in out.summary


@pytest.mark.asyncio
async def test_write_tool_paths_are_reflected_in_report(monkeypatch):
    rt = ToolRuntime()

    def code_replace(path, old, new, count=1):
        return {"path": path, "replacements": 1}

    rt.register("code_replace", code_replace)
    _seq(monkeypatch, [
        {"tool": "code_replace", "args": {"path": "static/styles.css", "old": "a", "new": "b"}},
        {
            "final": {
                "summary": "Cambio aplicado",
                "changed_files": [],
                "tests_run": [],
                "status": "done",
            }
        },
    ])
    agent = ToolExecutingAgent(_impl_spec(id="implementador_funcionalidades"), runtime=rt)

    out = await agent.run({"feature_request": "cambia botones"})

    assert out.status == "done"
    assert out.changed_files == ["static/styles.css"]


@pytest.mark.asyncio
async def test_false_done_gets_feedback_then_can_write(monkeypatch):
    rt = ToolRuntime()

    def code_replace(path, old, new, count=1):
        return {"path": path, "replacements": 1}

    rt.register("code_replace", code_replace)
    _seq(monkeypatch, [
        {
            "final": {
                "summary": "Cambio aplicado sin tool",
                "changed_files": [],
                "tests_run": [],
                "status": "done",
            }
        },
        {"tool": "code_replace", "args": {"path": "static/styles.css", "old": "a", "new": "b"}},
        {
            "final": {
                "summary": "Cambio aplicado con tool",
                "changed_files": [],
                "tests_run": [],
                "status": "done",
            }
        },
    ])
    agent = ToolExecutingAgent(_impl_spec(max_tool_steps=3), runtime=rt)

    out = await agent.run({"feature_request": "cambia botones"})

    assert out.status == "done"
    assert out.changed_files == ["static/styles.css"]


@pytest.mark.asyncio
async def test_implementer_css_button_fallback_edits_accent(monkeypatch, tmp_path):
    from agent_os.factory import code_tools

    root = tmp_path / "paradax"
    styles = root / "local-agent-os" / "static" / "styles.css"
    styles.parent.mkdir(parents=True)
    styles.write_text(":root {\n  --accent:    #7c3aed;\n}\n", encoding="utf-8")
    monkeypatch.setattr(code_tools, "PARADAX_ROOT", root)

    rt = ToolRuntime()
    _seq(monkeypatch, [
        {
            "final": {
                "summary": "No pude escribir",
                "changed_files": [],
                "tests_run": [],
                "status": "blocked",
            }
        }
    ])
    agent = ToolExecutingAgent(_impl_spec(id="implementador_funcionalidades"), runtime=rt)

    out = await agent.run({"feature_request": "cambia botones a #14b8a6"})

    assert out.status == "done"
    assert out.changed_files == ["local-agent-os/static/styles.css"]
    assert "#14b8a6" in styles.read_text(encoding="utf-8")


def test_make_agent_picks_class():
    assert isinstance(make_agent(_spec()), ToolExecutingAgent)
    plain = _spec(uses_tools=False)
    assert isinstance(make_agent(plain), ConstructedAgent)
