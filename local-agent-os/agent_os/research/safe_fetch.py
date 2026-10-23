from __future__ import annotations

"""Lector web seguro.

Barreras:
  - Solo http/https y solo GET. Nada de formularios, cookies ni sesiones.
  - Antes de cada salto (incluidas las redirecciones, que se siguen a mano)
    se resuelve el dominio y se rechaza si CUALQUIER dirección es local,
    privada, de enlace local, multicast o reservada. Así una página no puede
    llevar al lector hacia tu propio Mac (p. ej. la API de Paradax en
    127.0.0.1) ni hacia tu red de casa.
  - Límites: 3 redirecciones, 15 s, 1,5 MB descargados, solo tipos de texto.
  - El HTML se convierte a texto plano: scripts y estilos se descartan.
"""

import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

MAX_BYTES = 1_500_000
MAX_REDIRECTS = 3
TIMEOUT = 15
TEXT_TYPES = ("text/html", "text/plain", "application/json", "application/xhtml+xml", "text/markdown")
USER_AGENT = "ParadaxResearcher/1.0 (+lectura de texto, local)"


class FetchError(RuntimeError):
    pass


def check_url(url: str) -> str:
    """Valida esquema y destino. Devuelve la URL o lanza FetchError."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise FetchError(f"esquema no permitido: {parts.scheme or '(vacío)'}")
    if not parts.hostname:
        raise FetchError("URL sin dominio")
    if parts.username or parts.password:
        raise FetchError("URL con credenciales")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise FetchError(f"no se pudo resolver {parts.hostname}") from exc
    for info in infos:
        _check_ip(info[4][0], parts.hostname)
    return url


def _check_ip(addr: str, host: str = "") -> None:
    ip = ipaddress.ip_address(addr.split("%")[0])
    if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
            or ip.is_reserved or ip.is_unspecified):
        raise FetchError(f"destino local o privado bloqueado: {host or addr} → {ip}")


def _check_peer(resp: httpx.Response) -> None:
    """Segunda barrera contra DNS rebinding: el dominio pudo resolver a una IP
    pública al validar y a 127.0.0.1 al conectar. Se mira la IP REAL de la
    conexión antes de leer el cuerpo."""
    stream = resp.extensions.get("network_stream")
    peer = stream.get_extra_info("server_addr") if stream is not None else None
    if not peer:
        raise FetchError("no se pudo verificar la dirección de la conexión")
    _check_ip(peer[0])


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "head"}
    BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "tr", "section", "article", "pre", "td"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    p = _Text()
    try:
        p.feed(html)
    except Exception:  # noqa: BLE001 — HTML roto: se usa lo que se pudo leer
        pass
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.parts))
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return p.title.strip(), text


def fetch_text(url: str, max_chars: int = 20_000) -> dict:
    """GET seguro. Devuelve {url, title, text, truncated}."""
    current = url
    with httpx.Client(timeout=TIMEOUT, follow_redirects=False,
                      headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1"}) as client:
        for _ in range(MAX_REDIRECTS + 1):
            check_url(current)
            with client.stream("GET", current) as resp:
                _check_peer(resp)
                if resp.is_redirect:
                    location = resp.headers.get("location", "")
                    if not location:
                        raise FetchError("redirección sin destino")
                    current = urljoin(current, location)
                    continue
                if resp.status_code >= 400:
                    raise FetchError(f"HTTP {resp.status_code}")
                ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype and not ctype.startswith(TEXT_TYPES):
                    raise FetchError(f"tipo no textual: {ctype}")
                body = b""
                for chunk in resp.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        break
                raw = body[:MAX_BYTES].decode(resp.encoding or "utf-8", errors="replace")
            title, text = html_to_text(raw) if "html" in ctype or raw.lstrip().startswith("<") else ("", raw)
            return {"url": current, "title": title[:200], "text": text[:max_chars], "truncated": len(text) > max_chars}
    raise FetchError("demasiadas redirecciones")
