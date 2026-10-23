from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.agent import Agent
from ..core.contract import AgentContract
from ..core.schemas import ReelResult
from ..tools import media


class VideoBuilderAgent(Agent):
    """Convierte GIF + guion en un reel MP4 con voz y música (make_reel.sh)."""

    contract = AgentContract(
        id="video_builder",
        name="Video Builder",
        description="Monta el reel MP4 con voz narrada y música",
        reads=("gif", "voice", "language", "music"),
        writes="reel",
        output_model=ReelResult,
        allowed_tools=("make_reel",),
    )

    async def execute(self, ctx: dict[str, Any]) -> ReelResult:
        gif_path = ctx["gif"]["path"]
        # El nombre del reel se deriva del GIF realmente usado (puede ser el
        # reparado, no el del plan original).
        gif_stem = Path(gif_path).stem
        reel_name = f"reel-{gif_stem.removeprefix('gif-')}-{ctx['language']}.mp4"
        result = media.make_reel(
            gif_path, ctx["voice"]["text"], ctx["language"], ctx["music"], reel_name
        )
        return ReelResult.model_validate(result)
