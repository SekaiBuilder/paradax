from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from ..config import MEDIA_MANAGER_ROOT


class ToolError(RuntimeError):
    pass


def active_project() -> dict[str, str]:
    active_path = MEDIA_MANAGER_ROOT / "proyectos" / "ACTIVO.txt"
    if not active_path.exists():
        raise ToolError(f"Missing active project file: {active_path}")
    name = active_path.read_text(encoding="utf-8").strip()
    project_path = MEDIA_MANAGER_ROOT / "proyectos" / f"{name}.md"
    if not project_path.exists():
        raise ToolError(f"Missing project file: {project_path}")
    text = project_path.read_text(encoding="utf-8")
    url = _extract_project_url(text)
    if not url:
        raise ToolError(f"Project file has no URL de la página: {project_path}")
    return {"name": name, "path": str(project_path), "url": url}


def write_actions(name: str, actions: list[dict[str, Any]]) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", name):
        raise ToolError("Action file name must be simple ASCII")
    path = MEDIA_MANAGER_ROOT / "recorder" / name
    if path.suffix != ".json":
        path = path.with_suffix(".json")
    path.write_text(json.dumps(actions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def record_page_gif(url: str, actions_file: str | Path, output_name: str) -> dict[str, Any]:
    recorder = MEDIA_MANAGER_ROOT / "recorder"
    script = recorder / "grabar_gif.js"
    output = MEDIA_MANAGER_ROOT / "gifs" / output_name
    if output.suffix != ".gif":
        output = output.with_suffix(".gif")
    if not script.exists():
        raise ToolError(f"Recorder script not found: {script}")
    actions_path = Path(actions_file)
    if not actions_path.is_absolute():
        actions_path = recorder / actions_path
    # 180s: una coreografía larga con varios selectores fallidos (5s c/u) +
    # conversión a GIF puede superar 90s sin que sea un cuelgue real.
    result = _run(["node", str(script), url, str(actions_path), str(output)], cwd=recorder, timeout=180)
    verification = verify_media(output)
    # El recorder avisa cada selector que no encontró: contarlos permite al
    # orquestador decidir la reparación sin adivinar sobre el stderr completo.
    failed_steps = _count_failed_steps(result)
    return {
        "path": str(output),
        "log": result,
        "verification": verification,
        "failed_steps": failed_steps,
    }


def _count_failed_steps(result: dict[str, Any]) -> int:
    text = (result.get("stderr") or "") + "\n" + (result.get("stdout") or "")
    return len(re.findall(r"paso falló", text))


def make_reel(gif_path: str | Path, script_text: str, language: str, music_path: str | Path, output_name: str) -> dict[str, Any]:
    scripts_dir = MEDIA_MANAGER_ROOT / "scripts"
    make_script = scripts_dir / "make_reel.sh"
    gif = Path(gif_path)
    if not gif.is_absolute():
        gif = MEDIA_MANAGER_ROOT / "gifs" / gif
    music = Path(music_path)
    if not music.is_absolute():
        music = MEDIA_MANAGER_ROOT / "music" / music
    output = MEDIA_MANAGER_ROOT / "output" / output_name
    if output.suffix != ".mp4":
        output = output.with_suffix(".mp4")
    result = _run(
        [str(make_script), str(gif), script_text, language, str(music), str(output)],
        cwd=scripts_dir,
        timeout=180,
    )
    verification = verify_media(output)
    return {"path": str(output), "log": result, "verification": verification}


def verify_media(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise ToolError(f"Output file does not exist: {p}")
    probe = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=width,height,duration",
            "-show_entries",
            "format=duration,size",
            "-of",
            "json",
            str(p),
        ],
        cwd=p.parent,
        timeout=20,
    )
    data = json.loads(probe["stdout"] or "{}")
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video = next((s for s in streams if "width" in s and "height" in s), {})
    duration = float(fmt.get("duration") or video.get("duration") or 0)
    size = int(fmt.get("size") or p.stat().st_size)
    return {
        "exists": True,
        "path": str(p),
        "duration": duration,
        "size": size,
        "width": video.get("width"),
        "height": video.get("height"),
        "ok": duration > 1 and size > 20_000,
    }


def _extract_project_url(text: str) -> str | None:
    match = re.search(r"URL de la página\s*\n\s*(https?://\S+)", text, re.I)
    if match:
        return match.group(1).strip()
    match = re.search(r"https?://\S+", text)
    return match.group(0).strip() if match else None


def _run(argv: list[str], cwd: Path, timeout: int) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ToolError(
            json.dumps(
                {
                    "command": argv,
                    "cwd": str(cwd),
                    "error": f"timeout tras {timeout}s",
                    "stdout": (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
                    "stderr": (exc.stderr or b"").decode() if isinstance(exc.stderr, bytes) else (exc.stderr or ""),
                },
                ensure_ascii=False,
                indent=2,
            )
        ) from exc
    payload = {
        "command": argv,
        "cwd": str(cwd),
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
    if proc.returncode != 0:
        raise ToolError(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload
