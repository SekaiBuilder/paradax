from __future__ import annotations

import pytest

from agent_os.factory import code_executor


@pytest.mark.asyncio
async def test_detects_real_change(tmp_path):
    (tmp_path / "a.txt").write_text("antes", encoding="utf-8")

    async def fake_claude(prompt, cwd):
        (cwd / "a.txt").write_text("después", encoding="utf-8")   # edita
        (cwd / "nuevo.py").write_text("x = 1\n", encoding="utf-8")  # crea
        return '{"summary": "hecho", "changed_files": ["a.txt"], "status": "done"}'

    res = await code_executor.claude_execute("cambia a.txt", tmp_path, _claude=fake_claude)
    assert res["status"] == "done"
    assert set(res["changed_files"]) == {"a.txt", "nuevo.py"}  # detección determinista
    assert res["executor"] == "claude_code"


@pytest.mark.asyncio
async def test_no_change_is_blocked(tmp_path):
    (tmp_path / "a.txt").write_text("antes", encoding="utf-8")

    async def fake_claude(prompt, cwd):
        return '{"summary": "no hice nada", "status": "blocked"}'

    res = await code_executor.claude_execute("haz algo", tmp_path, _claude=fake_claude)
    assert res["status"] == "blocked"
    assert res["changed_files"] == []


@pytest.mark.asyncio
async def test_claude_error_is_blocked(tmp_path):
    async def boom(prompt, cwd):
        raise RuntimeError("claude no disponible")

    res = await code_executor.claude_execute("x", tmp_path, _claude=boom)
    assert res["status"] == "blocked"
    assert "claude no disponible" in res["error"]


def test_excluded_dirs_ignored(tmp_path):
    (tmp_path / "keep.py").write_text("a", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.pyc").write_text("b", encoding="utf-8")
    tree = code_executor._hash_tree(tmp_path)
    assert "keep.py" in tree
    assert not any("__pycache__" in p for p in tree)
