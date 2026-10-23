from __future__ import annotations

"""Modo IA: el Mac se dedica al entrenamiento y luego vuelve a la normalidad.

Al arrancar:
  1. Apps (PARADAX_APPS_MODE):
       quit  (por defecto) cierra con quit normal todas las apps visibles salvo
             Terminal y Finder, y apunta cuáles eran en runs/nightly/closed_apps.json.
             Libera la RAM de verdad. Al terminar (o con ESC) se REABREN.
       pause pausa (SIGSTOP) las apps pesadas. Libera CPU; la RAM la comprime
             macOS poco a poco. Al terminar se reanudan.
  2. Lanza `agent_os.training.nightly` y muestra su log.
  3. Cada minuto muestra presión de memoria, swap, disco libre y límite térmico
     (un MacBook Air no tiene ventilador: bajo carga larga, macOS reduce la
     velocidad). Si el disco baja de PARADAX_MIN_DISK_GB (20) PAUSA el
     entrenamiento: un checkpoint a medio escribir con el disco lleno se corrompe.

Teclas:
  ESC  pausa el entrenamiento y te DEVUELVE el Mac (reabre/reanuda tus apps)
  R    reanuda el entrenamiento y vuelve a pausar las apps
  C    CIERRA todas tus apps (cierre normal: cada app guarda su estado y
       pregunta si hay algo sin guardar). Libera la RAM de verdad.
  Q    termina el entrenamiento y sale

Pase lo que pase (Q, Ctrl+C, cierre de ventana, error), al salir se reanudan
las apps pausadas y se reabren las cerradas: tu entorno vuelve solo.

Uso:
    .venv/bin/python -m agent_os.training.night_console
    .venv/bin/python -m agent_os.training.night_console --dry-run   # solo lista qué pausaría
"""

import argparse
import atexit
import json
import os
import select
import signal
import subprocess
import sys
import termios
import time
import tty
from datetime import datetime

from ..config import ROOT

# Procesos que NUNCA se pausan: la propia consola y lo que entrena.
WHITELIST = ("Terminal", "iTerm", "Ollama", "ollama", "python", "Python", "caffeinate", "Claude", "claude")
MIN_RSS_MB = int(os.getenv("PARADAX_PAUSE_MIN_MB", "30"))

BLACK = "\033[40m\033[37m"
DIM, BOLD, GREEN, YELLOW, RESET = "\033[2m", "\033[1m", "\033[32m", "\033[33m", "\033[0m"

APPS_MODE = os.getenv("PARADAX_APPS_MODE", "quit")
MIN_DISK_GB = float(os.getenv("PARADAX_MIN_DISK_GB", "20"))
MONITOR_EVERY_S = 60
CLOSED_FILE = ROOT / "runs" / "nightly" / "closed_apps.json"
PAUSED_FILE = ROOT / "runs" / "nightly" / "paused_pids.json"

# Servicios de macOS en segundo plano que se pueden PAUSAR sin riesgo: son
# análisis, indexado y sincronización que retoman su trabajo al reanudarse.
# Lista explícita a propósito: congelar WindowServer, cfprefsd, launchd o el
# compilador de Metal (que la GPU necesita para entrenar) colgaría el Mac.
# Los que corren como root (mds_stores, el indexador de Spotlight) no se
# pueden pausar sin sudo y se saltan solos.
BACKGROUND_PAUSABLE = (
    "mediaanalysisd", "photoanalysisd", "photolibraryd", "corespotlightd",
    "Spotlight", "contactsd", "duetexpertd", "suggestd", "knowledge-agent",
    "bird", "cloudd", "nsurlsessiond", "WallpaperImageExtension",
    "WallpaperAgent", "mediaremoteagent", "biomesyncd", "routined",
    "triald", "siriknowledged", "parsecd", "spotlightknowledged",
)

_paused: list[int] = []
_closed: list[str] = []


def heavy_apps() -> list[tuple[int, int, str]]:
    """(pid, rss_mb, nombre) de las apps de /Applications que superan MIN_RSS_MB."""
    out = subprocess.run(["ps", "-axo", "pid=,rss=,comm="], capture_output=True, text=True).stdout
    me = os.getpid()
    apps = []
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        pid, rss, comm = int(parts[0]), int(parts[1]) // 1024, parts[2]
        if pid == me or "/Applications/" not in comm or rss < MIN_RSS_MB:
            continue
        name = comm.split("/Applications/", 1)[1].split(".app", 1)[0]
        if any(w in comm for w in WHITELIST):
            continue
        apps.append((pid, rss, name))
    return sorted(apps, key=lambda a: -a[1])


KEEP_OPEN = ("Terminal", "Finder")


def quit_apps(keep: tuple[str, ...] = KEEP_OPEN) -> list[str]:
    """Cierra con 'quit' normal todas las apps visibles salvo `keep`. A
    diferencia de matar procesos, cada app guarda su estado al salir."""
    script = 'tell application "System Events" to get name of every application process whose background only is false'
    out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=20).stdout
    names = [n.strip() for n in out.split(",") if n.strip() and n.strip() not in keep]
    for name in names:
        subprocess.run(["osascript", "-e", f'tell application "{name}" to quit'],
                       capture_output=True, timeout=30)
    return names


def close_apps() -> list[str]:
    """Cierra las apps y las apunta (también en disco, por si la consola muere:
    `--restore` las reabre después)."""
    names = quit_apps()
    _closed.extend(n for n in names if n not in _closed)
    CLOSED_FILE.parent.mkdir(parents=True, exist_ok=True)
    CLOSED_FILE.write_text(json.dumps(_closed, ensure_ascii=False), encoding="utf-8")
    return names


def reopen_apps() -> list[str]:
    names = list(_closed)
    if not names and CLOSED_FILE.exists():
        try:
            names = json.loads(CLOSED_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            names = []
    for name in names:
        # -g: en segundo plano, sin robar el foco a la consola.
        subprocess.run(["open", "-g", "-a", name], capture_output=True, timeout=30)
    _closed.clear()
    CLOSED_FILE.unlink(missing_ok=True)
    return names


def free_mac() -> str:
    """Libera recursos según APPS_MODE; devuelve el resumen para la consola."""
    if APPS_MODE == "pause":
        mb = pause_apps()
        apps = f"{len(_paused)} procesos de apps pausados (~{mb / 1024:.1f} GB)"
    else:
        names = close_apps()
        apps = f"{len(names)} apps cerradas: {', '.join(names) or 'ninguna'}"
    before = len(_paused)
    bg = pause_background()
    return f"{apps} · {len(_paused) - before} servicios en segundo plano pausados (~{bg / 1024:.1f} GB)"


def give_back_mac() -> None:
    resume_apps()
    reopen_apps()


def stats() -> dict[str, float]:
    """Métricas sin sudo: presión de memoria, swap, disco y límite térmico."""
    out: dict[str, float] = {}
    try:
        mp = subprocess.run(["memory_pressure"], capture_output=True, text=True, timeout=10).stdout
        out["mem_free_pct"] = float(mp.rsplit("percentage:", 1)[1].strip().rstrip("%"))
    except Exception:
        pass
    try:
        sw = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True, timeout=5).stdout
        out["swap_gb"] = float(sw.split("used = ")[1].split("M")[0]) / 1024
    except Exception:
        pass
    try:
        st = os.statvfs(str(ROOT))
        out["disk_free_gb"] = st.f_bavail * st.f_frsize / 1024**3
    except OSError:
        pass
    try:
        th = subprocess.run(["pmset", "-g", "therm"], capture_output=True, text=True, timeout=5).stdout
        if "CPU_Speed_Limit" in th:
            out["cpu_speed_limit"] = float(th.split("CPU_Speed_Limit")[1].split("=")[1].split()[0])
    except Exception:
        pass
    return out


def stats_line(st: dict[str, float]) -> str:
    parts = []
    if "mem_free_pct" in st:
        parts.append(f"RAM libre {st['mem_free_pct']:.0f}%")
    if "swap_gb" in st:
        parts.append(f"swap {st['swap_gb']:.1f} GB")
    if "disk_free_gb" in st:
        parts.append(f"disco {st['disk_free_gb']:.0f} GB")
    limit = st.get("cpu_speed_limit", 100)
    parts.append("térmica OK" if limit >= 100 else f"🔥 CPU limitada al {limit:.0f}%")
    return " · ".join(parts)


def pause_apps() -> int:
    total = 0
    for pid, rss, _name in heavy_apps():
        try:
            os.kill(pid, signal.SIGSTOP)
            _paused.append(pid)
            total += rss
        except (ProcessLookupError, PermissionError):
            pass
    _save_paused()
    return total


def pause_background() -> int:
    """Pausa los servicios de BACKGROUND_PAUSABLE y los auxiliares de apps de
    usuario (~/Library/Application Support). Solo procesos del usuario."""
    out = subprocess.run(["ps", "-U", str(os.getuid()), "-axo", "pid=,rss=,comm="],
                         capture_output=True, text=True).stdout
    total = 0
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        pid, rss, comm = int(parts[0]), int(parts[1]) // 1024, parts[2]
        name = comm.rsplit("/", 1)[-1]
        helper = "/Library/Application Support/" in comm and rss >= MIN_RSS_MB
        if pid == os.getpid() or pid in _paused or not (name in BACKGROUND_PAUSABLE or helper):
            continue
        if any(w in comm for w in WHITELIST):
            continue
        try:
            os.kill(pid, signal.SIGSTOP)
            _paused.append(pid)
            total += rss
        except (ProcessLookupError, PermissionError):
            pass
    _save_paused()
    return total


def _save_paused() -> None:
    try:
        PAUSED_FILE.parent.mkdir(parents=True, exist_ok=True)
        PAUSED_FILE.write_text(json.dumps(_paused), encoding="utf-8")
    except OSError:
        pass


def resume_apps() -> None:
    if not _paused and PAUSED_FILE.exists():  # consola anterior interrumpida
        try:
            _paused.extend(json.loads(PAUSED_FILE.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    PAUSED_FILE.unlink(missing_ok=True)
    while _paused:
        pid = _paused.pop()
        try:
            os.kill(pid, signal.SIGCONT)
        except (ProcessLookupError, PermissionError):
            pass


def _say(msg: str, color: str = "") -> None:
    sys.stdout.write(f"{BLACK}{DIM}{datetime.now():%H:%M:%S}{RESET}{BLACK} {color}{msg}{RESET}{BLACK}\r\n")
    sys.stdout.flush()


def _header() -> None:
    sys.stdout.write(f"{BLACK}\033[2J\033[H")
    sys.stdout.write(f"{BOLD}  PARADAX · MODO IA{RESET}{BLACK}\r\n")
    sys.stdout.write(f"{DIM}  ESC pausa y te devuelve el Mac · R reanuda · C cierra todas las apps · Q termina y restaura{RESET}{BLACK}\r\n\r\n")
    sys.stdout.flush()


def run(dry_run: bool) -> int:
    if dry_run:
        print(f"modo de apps: {APPS_MODE}")
        if APPS_MODE == "pause":
            apps = heavy_apps()
            for pid, rss, name in apps:
                print(f"pausaría  {rss:>6} MB  {name} ({pid})")
            print(f"total ≈ {sum(a[1] for a in apps) / 1024:.1f} GB en {len(apps)} procesos")
        else:
            script = 'tell application "System Events" to get name of every application process whose background only is false'
            out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=20).stdout
            names = [n.strip() for n in out.split(",") if n.strip() and n.strip() not in KEEP_OPEN]
            print(f"cerraría y reabriría después: {', '.join(names) or 'ninguna'}")
        out = subprocess.run(["ps", "-U", str(os.getuid()), "-axo", "rss=,comm="], capture_output=True, text=True).stdout
        bg = sorted({l.split(None, 1)[1].rsplit("/", 1)[-1] for l in out.splitlines()
                     if len(l.split(None, 1)) == 2 and l.split(None, 1)[1].rsplit("/", 1)[-1] in BACKGROUND_PAUSABLE})
        print(f"pausaría en segundo plano: {', '.join(bg) or 'ninguno'} + auxiliares de apps")
        print(stats_line(stats()))
        return 0

    sys.stdout.write("\033[9;1t")  # maximizar la ventana de Terminal
    _header()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    atexit.register(give_back_mac)
    atexit.register(lambda: termios.tcsetattr(fd, termios.TCSADRAIN, old))
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: sys.exit(0))

    _say(free_mac(), GREEN)
    _say(stats_line(stats()))

    log = open(ROOT / "runs" / "nightly" / f"night-{datetime.now():%Y%m%d}.log", "a", encoding="utf-8")
    child = subprocess.Popen(
        [sys.executable, "-u", "-m", "agent_os.training.nightly"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        start_new_session=True,  # grupo propio: pausar/terminar afecta a todo el entrenamiento
    )
    os.set_blocking(child.stdout.fileno(), False)
    training_paused = False
    disk_paused = False
    next_monitor = time.time() + MONITOR_EVERY_S
    tty.setcbreak(fd)
    try:
        while True:
            ready, _, _ = select.select([fd, child.stdout], [], [], 1.0)
            if child.stdout in ready:
                for line in iter(child.stdout.readline, ""):
                    log.write(line)
                    log.flush()
                    _say(line.rstrip()[9:] if line[:2].isdigit() else line.rstrip())
            if child.poll() is not None:
                _say(f"entrenamiento terminado (código {child.returncode}) · restaurando tu Mac", GREEN)
                give_back_mac()
                time.sleep(5)
                return child.returncode
            if time.time() >= next_monitor:
                next_monitor = time.time() + MONITOR_EVERY_S
                st = stats()
                _say(stats_line(st), DIM)
                disk = st.get("disk_free_gb", 1e9)
                if disk < MIN_DISK_GB and not training_paused:
                    os.killpg(child.pid, signal.SIGSTOP)
                    training_paused = disk_paused = True
                    _say(f"⛔ disco casi lleno ({disk:.0f} GB): entrenamiento en PAUSA · libera espacio y pulsa R", YELLOW)
                elif disk_paused and disk >= MIN_DISK_GB + 5:
                    os.killpg(child.pid, signal.SIGCONT)
                    training_paused = disk_paused = False
                    _say("▶  hay espacio otra vez: entrenamiento reanudado", GREEN)
            if fd in ready:
                key = os.read(fd, 1)
                if key == b"\x1b" and not training_paused:
                    os.killpg(child.pid, signal.SIGSTOP)
                    give_back_mac()
                    training_paused = True
                    _say("⏸  entrenamiento en pausa · tus apps vuelven · R reanuda · Q termina", YELLOW)
                elif key in (b"r", b"R") and training_paused:
                    summary = free_mac()
                    os.killpg(child.pid, signal.SIGCONT)
                    training_paused = disk_paused = False
                    _say(f"▶  reanudado · {summary}", GREEN)
                elif key in (b"c", b"C"):
                    resume_apps()  # una app pausada no puede atender el quit
                    _say("cerrando todas las apps…", YELLOW)
                    closed = close_apps()
                    _say(f"cerradas: {', '.join(closed) or 'ninguna'}", GREEN)
                elif key in (b"q", b"Q"):
                    _say("terminando…", YELLOW)
                    os.killpg(child.pid, signal.SIGCONT)
                    os.killpg(child.pid, signal.SIGTERM)
                    child.wait(timeout=30)
                    give_back_mac()
                    _say("tu Mac está restaurado", GREEN)
                    return 0
    finally:
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGCONT)
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        give_back_mac()
        log.close()
        sys.stdout.write(RESET + "\r\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Consola nocturna de entrenamiento")
    parser.add_argument("--dry-run", action="store_true", help="solo muestra qué haría y las métricas")
    parser.add_argument("--restore", action="store_true", help="reabre las apps que cerró un Modo IA interrumpido")
    args = parser.parse_args()
    if args.restore:
        resume_apps()
        print("procesos reanudados · reabiertas:", ", ".join(reopen_apps()) or "ninguna")
        # Lo primero que ves al levantarte: el informe de la noche.
        from .morning_report import NIGHTLY, open_report
        if (NIGHTLY / f"night-{datetime.now():%Y%m%d}.log").exists():
            print("informe:", open_report())
        sys.exit(0)
    sys.exit(run(args.dry_run))


if __name__ == "__main__":
    main()
