from __future__ import annotations

import httpx
import pytest

from agent_os.agents.page_inspector import PageInspectorAgent

HTML = """
<html><body>
  <button id="btn-kanji" class="nav-btn primary">Kanji</button>
  <div id="tut-x" class="tut-close"></div>
  <td class="kanji-clickable" data-study-type="kanji">水</td>
  <button class="btn-quiz-modal" data-quiz-mode="auto">Quiz</button>
</body></html>
"""


@pytest.mark.asyncio
async def test_extracts_real_selectors(monkeypatch):
    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, text=HTML, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    agent = PageInspectorAgent()
    result = await agent.run({"url": "https://kana.example.com"})

    assert result.fetched is True
    assert "btn-kanji" in result.ids
    assert "tut-x" in result.ids
    assert "kanji-clickable" in result.classes
    assert "[data-study-type='kanji']" in result.data_selectors
    assert "[data-quiz-mode='auto']" in result.data_selectors


@pytest.mark.asyncio
async def test_fetch_failure_returns_empty_inventory(monkeypatch):
    async def fake_get(self, url, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    agent = PageInspectorAgent()
    result = await agent.run({"url": "https://down.example.com"})

    assert result.fetched is False
    assert result.ids == []
    assert "ConnectError" in result.note


@pytest.mark.asyncio
async def test_missing_context_key_fails():
    from agent_os.core.agent import AgentError

    agent = PageInspectorAgent()
    with pytest.raises(AgentError, match="faltan claves"):
        await agent.run({})
