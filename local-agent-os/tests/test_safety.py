from __future__ import annotations

from agent_os.factory import safety


def test_ensure_repo_creates_repo_and_gitignore(tmp_path):
    (tmp_path / "code.py").write_text("x = 1\n", encoding="utf-8")
    assert safety.ensure_repo(tmp_path) is True
    assert safety.is_repo(tmp_path) is True
    assert (tmp_path / ".gitignore").exists()
    assert safety.current_sha(tmp_path)  # hay un commit baseline


def test_snapshot_undo_restores_file(tmp_path):
    f = tmp_path / "app.txt"
    f.write_text("original\n", encoding="utf-8")
    safety.ensure_repo(tmp_path)
    before = safety.snapshot("antes", root=tmp_path)

    f.write_text("EDITADO POR UN AGENTE\n", encoding="utf-8")
    after = safety.snapshot("cambio del agente", root=tmp_path)

    assert before != after
    assert "app.txt" in safety.changed_files(before, root=tmp_path)

    res = safety.undo_to(before, root=tmp_path)
    assert res["ok"] is True
    assert f.read_text(encoding="utf-8") == "original\n"   # deshecho


def test_gitignore_excludes_heavy(tmp_path):
    safety.ensure_repo(tmp_path)
    (tmp_path / "big.gif").write_bytes(b"x" * 1000)
    (tmp_path / "keep.py").write_text("a", encoding="utf-8")
    safety.snapshot("añade archivos", root=tmp_path)
    # big.gif está ignorado; keep.py no
    tracked = safety._git(tmp_path, "ls-files").stdout
    assert "keep.py" in tracked
    assert "big.gif" not in tracked
