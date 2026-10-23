from __future__ import annotations

from pathlib import Path

import pytest

from agent_os.factory import code_tools


@pytest.fixture
def code_root(tmp_path, monkeypatch):
    root = tmp_path / "paradax"
    root.mkdir()
    monkeypatch.setattr(code_tools, "PARADAX_ROOT", root)
    return root


def test_code_read_and_replace_stay_inside_root(code_root: Path):
    target = code_root / "local-agent-os" / "demo.py"
    target.parent.mkdir()
    target.write_text("VALUE = 1\n", encoding="utf-8")

    read = code_tools.code_read_file("local-agent-os/demo.py")
    assert read["content"] == "VALUE = 1\n"

    changed = code_tools.code_replace("local-agent-os/demo.py", "VALUE = 1", "VALUE = 2")
    assert changed == {"path": "local-agent-os/demo.py", "replacements": 1}
    assert target.read_text(encoding="utf-8") == "VALUE = 2\n"


def test_code_tools_block_paths_outside_root(code_root: Path, tmp_path: Path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(ValueError):
        code_tools.code_read_file(str(outside))


def test_code_search_and_list_ignore_heavy_dirs(code_root: Path):
    app = code_root / "local-agent-os" / "app.py"
    app.parent.mkdir()
    app.write_text("def target():\n    return 'ok'\n", encoding="utf-8")
    vendored = code_root / "local-agent-os" / "node_modules" / "bad.js"
    vendored.parent.mkdir()
    vendored.write_text("target\n", encoding="utf-8")

    files = code_tools.code_list_files("**/*")
    assert "local-agent-os/app.py" in files["files"]
    assert "local-agent-os/node_modules/bad.js" not in files["files"]

    found = code_tools.code_search("target", glob="**/*")
    assert any("local-agent-os/app.py" in line for line in found["results"])
    assert not any("node_modules" in line for line in found["results"])


def test_code_tools_accept_common_path_aliases(code_root: Path):
    styles = code_root / "local-agent-os" / "static" / "styles.css"
    styles.parent.mkdir(parents=True)
    styles.write_text(".btn { background: purple; }\n", encoding="utf-8")

    listed = code_tools.code_list_files(path="local-agent-os/static")
    assert listed["files"] == ["local-agent-os/static/styles.css"]

    found = code_tools.code_search(text="background", directory="local-agent-os/static")
    assert any("local-agent-os/static/styles.css" in line for line in found["results"])

    read = code_tools.code_read_file(file="local-agent-os/static/styles.css")
    assert "purple" in read["content"]

    changed = code_tools.code_replace(filepath="local-agent-os/static/styles.css", old="purple", new="#14b8a6")
    assert changed["path"] == "local-agent-os/static/styles.css"
    assert "#14b8a6" in styles.read_text(encoding="utf-8")


def test_code_run_pytest_uses_pytest_without_shell(code_root: Path):
    project = code_root / "local-agent-os"
    tests = project / "tests"
    tests.mkdir(parents=True)
    (tests / "test_ok.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8")

    result = code_tools.code_run_pytest("tests/test_ok.py", cwd="local-agent-os", timeout_s=30)
    assert result["exit_code"] == 0
    assert "tests/test_ok.py" in result["command"]
