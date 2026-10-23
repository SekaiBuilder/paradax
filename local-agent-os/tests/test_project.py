from __future__ import annotations

from agent_os.factory.project import ProjectStore


def test_create_and_persist(tmp_path):
    store = ProjectStore(root=tmp_path / "projects")
    p = store.create("Social Media Manager", goal="publicar reels a diario")
    assert p.id == "social-media-manager"
    assert p.status == "draft"
    assert (tmp_path / "projects" / "social-media-manager.json").exists()


def test_reload_from_disk(tmp_path):
    store = ProjectStore(root=tmp_path / "projects")
    store.create("Mi Proyecto", goal="x")
    store2 = ProjectStore(root=tmp_path / "projects")
    assert [p.id for p in store2.all()] == ["mi-proyecto"]
    assert store2.get("mi-proyecto").goal == "x"


def test_duplicate_name_unique_id(tmp_path):
    store = ProjectStore(root=tmp_path / "projects")
    a = store.create("Proyecto")
    b = store.create("Proyecto")
    assert a.id != b.id and b.id == "proyecto-2"


def test_remove(tmp_path):
    store = ProjectStore(root=tmp_path / "projects")
    store.create("Temporal")
    assert store.remove("temporal") is True
    assert store.get("temporal") is None


def test_project_tasks_persist(tmp_path):
    store = ProjectStore(root=tmp_path / "projects")
    p = store.create("Auto", goal="mejorar app")
    task = p.add_task("agrega dark mode")
    p.update_task(task.id, status="completed", run_id="proj-auto-abc", result={"ran": ["a"]})
    store.save(p)

    reloaded = ProjectStore(root=tmp_path / "projects").get("auto")
    assert reloaded.tasks[0].request == "agrega dark mode"
    assert reloaded.tasks[0].status == "completed"
    assert reloaded.tasks[0].run_id == "proj-auto-abc"
