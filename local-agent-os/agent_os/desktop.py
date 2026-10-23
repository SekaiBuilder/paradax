from __future__ import annotations

"""Paradax como aplicación de escritorio nativa (macOS).

Envuelve el control center en una ventana WKWebView con pywebview:
- Si el servidor ya corre en el puerto, solo abre la ventana.
- Si no, lo arranca en un hilo y lo apaga al cerrar la ventana.

Uso directo:   .venv/bin/python -m agent_os.desktop
Como app:      doble click en "Paradax.app" (ver scripts/make_app.sh)
"""

import os
import socket
import threading
import time
import urllib.request
from pathlib import Path

import webview

HOST = "127.0.0.1"
# 8787 lo ocupaba otro proyecto (exodus); Paradax usa 8791. Override con
# PARADAX_PORT si algún día también choca.
PORT = int(os.getenv("PARADAX_PORT", "8791"))
URL = f"http://{HOST}:{PORT}"
ICON_PNG = Path(__file__).resolve().parents[1] / "scripts" / "icon.iconset" / "icon_512x512.png"


def port_in_use() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((HOST, PORT)) == 0


def start_server() -> None:
    import uvicorn

    from .server import app

    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    server.run()


def _set_dock_icon() -> None:
    """Pone el icono de Agent OS en el Dock. DEBE correr en el hilo principal:
    toda mutación de NSApplication desde otro hilo dispara SIGTRAP (aserción
    de dispatch de Cocoa)."""
    try:
        from AppKit import NSApplication, NSImage

        app = NSApplication.sharedApplication()
        image = NSImage.alloc().initByReferencingFile_(str(ICON_PNG))
        if app is not None and image is not None:
            app.setApplicationIconImage_(image)
    except Exception:
        pass  # branding es cosmético: jamás debe tumbar la app


def brand_dock() -> None:
    """Agenda el icono del Dock en el hilo principal vía el run loop de Cocoa.

    pywebview corre bajo el python del venv (bundle org.python.python), así que
    sin esto el Dock muestra el icono genérico de Python. callLater encola
    _set_dock_icon en el run loop que webview.start() arranca en el hilo
    principal — el único lugar seguro para tocar NSApplication. El nombre
    'Agent OS' del menú lo aporta el .app bundle vía CFBundleName.
    """
    if not ICON_PNG.exists():
        return
    try:
        from PyObjCTools import AppHelper

        AppHelper.callLater(0.5, _set_dock_icon)
    except Exception:
        pass


def wait_for_health(timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{URL}/api/health", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def main() -> None:
    we_started_it = False
    if not port_in_use():
        thread = threading.Thread(target=start_server, daemon=True)
        thread.start()
        we_started_it = True

    if not wait_for_health():
        raise SystemExit(f"El servidor no respondió en {URL}/api/health")

    webview.create_window(
        "Paradax",
        URL,
        width=1280,
        height=820,
        min_size=(900, 600),
    )
    brand_dock()  # encola el icono en el run loop; corre al arrancar webview
    # El hilo del servidor es daemon: si lo arrancamos nosotros, muere con la
    # app al cerrar la ventana. Si ya corría (uvicorn externo), no se toca.
    webview.start()
    if we_started_it:
        pass  # daemon thread: se apaga al salir del proceso


if __name__ == "__main__":
    main()
