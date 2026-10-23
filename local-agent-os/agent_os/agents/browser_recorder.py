from __future__ import annotations

from typing import Any

from ..core.agent import Agent
from ..core.contract import AgentContract
from ..core.schemas import GifResult
from ..tools import media


class BrowserRecorderAgent(Agent):
    """Ejecuta el plan contra la página real con Playwright y produce el GIF.

    No usa LLM: escribe el archivo de acciones y lanza recorder/grabar_gif.js.
    """

    contract = AgentContract(
        id="browser_recorder",
        name="Browser Recorder",
        description="Graba la página real con Playwright y genera el GIF",
        reads=("url", "plan"),
        writes="gif",
        output_model=GifResult,
        allowed_tools=("write_actions", "record_page_gif"),
    )

    async def execute(self, ctx: dict[str, Any]) -> GifResult:
        plan = ctx["plan"]
        actions_file = media.write_actions(plan["actions_file_name"], plan["actions"])
        result = media.record_page_gif(ctx["url"], actions_file, plan["gif_output_name"])
        return GifResult.model_validate(result)
