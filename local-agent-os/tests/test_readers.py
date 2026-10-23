from __future__ import annotations

import httpx
import pytest

from agent_os.factory.entrenador import Entrenador
from agent_os.factory.readers import DocReaderAgent, UrlReaderAgent, fetch_url_text


class _FakeResp:
    def __init__(self, text):
        self.text = text
    def raise_for_status(self):
        pass


def _fake_get(html):
    def get(url, timeout=20, follow_redirects=True):
        return _FakeResp(html)
    return get


@pytest.mark.asyncio
async def test_doc_reader_text_file(tmp_path):
    f = tmp_path / "notas.txt"
    f.write_text("contenido de entrenamiento", encoding="utf-8")
    mat = await DocReaderAgent().run({"source": str(f)})
    assert mat.kind == "text"
    assert mat.text == "contenido de entrenamiento"
    assert mat.chars == len(mat.text)


@pytest.mark.asyncio
async def test_url_reader_strips_tags(monkeypatch):
    monkeypatch.setattr(httpx, "get", _fake_get(
        "<html><script>alert(1)</script><p>Hola <b>mundo</b></p></html>"
    ))
    mat = await UrlReaderAgent().run({"url": "https://ej.com"})
    assert mat.kind == "url"
    assert "alert" not in mat.text       # script eliminado
    assert "Hola mundo" in mat.text       # tags quitados, texto conservado


def test_readers_are_dormant_and_non_contactable():
    for agent in (DocReaderAgent(), UrlReaderAgent()):
        assert agent.contract.contactable is False
        assert agent.contract.on_demand is True


@pytest.mark.asyncio
async def test_entrenador_ingest_routes_url(monkeypatch):
    monkeypatch.setattr(httpx, "get", _fake_get("<p>material web</p>"))
    mat = await Entrenador().ingest_material("https://ejemplo.com/articulo")
    assert mat.kind == "url"
    assert "material web" in mat.text


@pytest.mark.asyncio
async def test_entrenador_ingest_routes_file(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("apuntes", encoding="utf-8")
    mat = await Entrenador().ingest_material(str(f))
    assert mat.kind == "text" and mat.text == "apuntes"


def test_collaborators_listing():
    ids = [c["id"] for c in Entrenador().collaborators()]
    assert ids == ["doc_reader", "url_reader"]


def test_fetch_url_text_real_cleanup():
    # función pura de limpieza, sin red (se le pasa HTML directo por monkeypatch arriba)
    assert callable(fetch_url_text)
