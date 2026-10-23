import pytest

from agent_os.factory.skill import Skill
from agent_os.factory.skill_master import SkillMaster


@pytest.fixture
def sm(tmp_path):
    master = SkillMaster(root=tmp_path / "skills")
    master.add(Skill(
        id="web-selectors", name="Selectores reales", kind="capability",
        description="ids y clases reales", tags=["web", "selectores"], tools=["http_get"],
    ))
    master.add(Skill(
        id="voice-es", name="Guion de voz", kind="prompt",
        description="locución corta", tags=["media", "tts"],
    ))
    master.add(Skill(
        id="hard-verify", name="Verificación dura", kind="eval",
        description="ffprobe y duración mínima", tags=["media", "verificacion"],
    ))
    return master


def test_add_get_len(sm):
    assert len(sm) == 3
    assert sm.get("web-selectors").name == "Selectores reales"
    assert sm.get("missing") is None


def test_persists_in_compact_form(sm, tmp_path):
    path = tmp_path / "skills" / "web-selectors.skw"
    assert path.exists()
    # el archivo está en formato compacto (short-keys), no verboso
    text = path.read_text(encoding="utf-8")
    assert '"i":"web-selectors"' in text
    assert "description" not in text  # campo verboso ausente


def test_reload_from_disk(sm):
    reloaded = SkillMaster(root=sm.root)
    assert len(reloaded) == 3
    assert {s.id for s in reloaded.all()} == {"web-selectors", "voice-es", "hard-verify"}
    assert reloaded.get("web-selectors") == sm.get("web-selectors")


def test_query_by_tags_ranks_overlap_first(sm):
    results = sm.query(tags=["media"])
    ids = [s.id for s in results]
    assert set(ids) == {"voice-es", "hard-verify"}
    assert "web-selectors" not in ids


def test_query_by_text(sm):
    results = sm.query(text="selectores reales")
    assert results and results[0].id == "web-selectors"


def test_query_by_kind(sm):
    results = sm.query(kind="eval")
    assert [s.id for s in results] == ["hard-verify"]


def test_remove(sm):
    assert sm.remove("voice-es") is True
    assert sm.get("voice-es") is None
    assert sm.remove("voice-es") is False
    assert not (sm.root / "voice-es.skw").exists()


def test_stats_reports_compression(sm):
    stats = sm.stats()
    assert stats["count"] == 3
    assert stats["compression"] >= 1.0
    assert stats["by_kind"]["eval"] == 1
