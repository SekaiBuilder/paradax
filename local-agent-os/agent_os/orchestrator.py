from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from . import db
from .agents import REGISTRY
from .agents.action_planner import ActionPlannerAgent, extract_kanji
from .config import DEFAULT_MODEL, RUNS_DIR
from .core.events import BUS
from .core.pipeline import Pipeline
from .core.schemas import Verdict


class MediaRunRequest(BaseModel):
    request: str = Field(..., min_length=3)
    model: str = DEFAULT_MODEL
    url: str | None = None
    make_reel: bool = True
    language: str = "es"
    music: str = "_placeholder-koto.mp3"


class UnsupportedMediaRequest(ValueError):
    """La petición no pertenece al pipeline de GIF/reel."""


_MEDIA_MARKERS = re.compile(
    r"\b(gif|reel|video|vídeo|mp4|graba|grabar|grabaci[oó]n|captura|screenshot|demo|demostraci[oó]n)\b",
    re.IGNORECASE,
)
_KANA_MARKERS = re.compile(
    r"\b(kanji|hiragana|katakana|kana\s*trainer|flashcards?|quiz|漢字)\b",
    re.IGNORECASE,
)


def is_media_request(text: str) -> bool:
    """Heurística conservadora para no convertir tareas de código en GIFs.

    El Media Manager es un pipeline específico de demos/GIF/reels. Si entra una
    petición de programación por aquí, el sistema acaba grabando el proyecto
    activo en vez de modificar código.
    """
    normalized = text.strip()
    if not normalized:
        return False
    if _MEDIA_MARKERS.search(normalized):
        return True
    if _KANA_MARKERS.search(normalized):
        return True
    return False


async def run_media_manager(req: MediaRunRequest) -> dict[str, Any]:
    """Orquestador del flujo de media. NO hace el trabajo: reparte y verifica.

        Usuario
          ↓
        Page Inspector   (selectores reales)
          ↓
        Action Planner   (plan validado contra esos selectores)
          ↓
        Browser Recorder (GIF desde la página real)
          ↓
        Verifier         (apto / reparar → 1 reintento con plan seguro)
          ↓
        Script Writer + Video Builder   (solo si se pidió reel)
          ↓
        Respuesta final
    """
    if not is_media_request(req.request):
        raise UnsupportedMediaRequest(
            "El Media Manager solo acepta pedidos de GIF/reel/demo. "
            "Para reprogramar Paradax usa un proyecto/agente con tools de código o Codex."
        )

    from .tools import media  # import tardío: facilita monkeypatch en tests

    db.init_db()
    run_id = _new_run_id(req.request)
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    db.create_run(run_id, "media_manager", req.request, req.model)
    _write_json(run_dir / "request.json", req.model_dump())
    BUS.publish("run_started", {"run_id": run_id, "request": req.request, "make_reel": req.make_reel})

    pipe = Pipeline(run_id)
    try:
        project = media.active_project()
        url = req.url or project["url"]
        db.add_event(run_id, "project_loaded", {"project": project, "url": url})

        # ── Page Inspector ──────────────────────────────────────────────
        inventory = await pipe.step(
            REGISTRY["page_inspector"],
            url=url,
            request=req.request,
            project=project,
            model=req.model,
            language=req.language,
            music=req.music,
        )
        _write_json(run_dir / "inventory.json", inventory.model_dump())

        # ── Action Planner ──────────────────────────────────────────────
        plan = await pipe.step(REGISTRY["action_planner"])
        _write_json(run_dir / "plan.json", plan.model_dump())

        # ── Browser Recorder + Verifier (con un ciclo de reparación) ────
        gif = await pipe.step(REGISTRY["browser_recorder"])
        verdict: Verdict = await pipe.step(REGISTRY["verifier"])

        initial_gif = None
        if verdict.should_repair:
            initial_gif = pipe.ctx["gif"]
            planner: ActionPlannerAgent = REGISTRY["action_planner"]  # type: ignore[assignment]
            repair = planner.repair_plan(req.request, run_id)
            _write_json(run_dir / "repair_plan.json", repair.model_dump())
            db.add_event(run_id, "gif_repair_started", {"reason": verdict.reason, "plan": repair.model_dump()})

            gif = await pipe.step(REGISTRY["browser_recorder"], plan=repair.model_dump())
            verdict = await pipe.step(REGISTRY["verifier"])

        output: dict[str, Any] = {
            "run_id": run_id,
            "project": project,
            "gif": pipe.ctx["gif"],
            "verdict": verdict.model_dump(),
            "plan_source": plan.plan_source,
        }
        if initial_gif:
            output["repaired"] = True
            output["initial_gif"] = initial_gif

        # ── Script Writer + Video Builder (solo si se pidió reel) ────────
        if req.make_reel:
            await pipe.step(REGISTRY["script_writer"])
            reel = await pipe.step(REGISTRY["video_builder"])
            output["reel"] = reel.model_dump()
            output["voice"] = pipe.ctx["voice"]

        _write_json(run_dir / "output.json", output)
        db.finish_run(run_id, "completed", output)
        BUS.publish("run_finished", {
            "run_id": run_id, "status": "completed",
            "gif": output.get("gif", {}).get("path"),
            "reel": output.get("reel", {}).get("path"),
        })
        return output
    except Exception as exc:
        db.add_event(run_id, "error", {"error": str(exc)})
        db.finish_run(run_id, "failed", error=str(exc))
        BUS.publish("run_finished", {"run_id": run_id, "status": "failed", "error": str(exc)[:300]})
        raise


def _new_run_id(text: str) -> str:
    return f"{_topic_slug(text)}-{uuid.uuid4().hex[:8]}"


def _topic_slug(text: str) -> str:
    kanji = extract_kanji(text)
    if kanji:
        return f"kanji-{ord(kanji):x}"
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (slug[:48] or "media-run").strip("-")


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
