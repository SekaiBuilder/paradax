from __future__ import annotations

from agent_os.sandbox.tool_broker import ToolBroker


def test_media_task_kind():
    broker = ToolBroker.for_task("r1", "media")
    assert broker.is_allowed("record_page_gif")
    assert broker.is_allowed("make_reel")
    assert not broker.is_allowed("code_replace")


def test_code_task_kind():
    broker = ToolBroker.for_task("r1", "code")
    assert broker.is_allowed("code_read_file")
    assert broker.is_allowed("code_replace")
    assert not broker.is_allowed("record_page_gif")


def test_jobsearch_task_kind():
    broker = ToolBroker.for_task("r1", "jobsearch")
    assert broker.is_allowed("http_get")
    assert not broker.is_allowed("code_write_file")


def test_unknown_task_kind_is_empty():
    broker = ToolBroker.for_task("r1", "unknown_kind")
    assert not broker.is_allowed("code_read_file")
    assert not broker.is_allowed("http_get")


def test_unrestricted_allows_all():
    broker = ToolBroker.unrestricted("r1")
    assert broker.is_allowed("code_read_file")
    assert broker.is_allowed("record_page_gif")
    assert broker.is_allowed("http_get")
