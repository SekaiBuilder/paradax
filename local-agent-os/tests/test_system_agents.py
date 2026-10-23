from __future__ import annotations

from agent_os.factory import system_agents as sa


def test_contactability_flags():
    assert sa.is_contactable("entrenador") is True
    assert sa.is_contactable("constructor") is True
    assert sa.is_contactable("doc_reader") is False   # colaborador durmiente
    assert sa.is_contactable("url_reader") is False
    assert sa.is_contactable("auditor") is False
    assert sa.is_contactable("ghost") is False


def test_is_system_agent():
    assert sa.is_system_agent("entrenador") is True
    assert sa.is_system_agent("redactor_post") is False  # agente de proyecto


def test_graph_has_reader_edges():
    g = sa.graph()
    ids = {a["id"] for a in g["agents"]}
    assert {"doc_reader", "url_reader"} <= ids
    edges = {(e["from"], e["to"]) for e in g["edges"]}
    assert ("entrenador", "doc_reader") in edges
    assert ("entrenador", "url_reader") in edges


def test_dormant_collaborators_marked():
    by_id = {a["id"]: a for a in sa.SYSTEM_AGENTS}
    assert by_id["doc_reader"]["on_demand"] is True
    assert by_id["url_reader"]["on_demand"] is True


def test_project_visibility_filter():
    from agent_os.server import _project_visible
    # sin filtro: solo agentes SIN proyecto
    assert _project_visible("", None) is True
    assert _project_visible("p1", None) is False
    # filtro por id: solo ese proyecto
    assert _project_visible("p1", "p1") is True
    assert _project_visible("p2", "p1") is False
    assert _project_visible("", "p1") is False
    # 'all': todos
    assert _project_visible("p1", "all") is True
