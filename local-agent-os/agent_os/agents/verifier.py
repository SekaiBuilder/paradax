from __future__ import annotations

from typing import Any

from ..core.agent import Agent
from ..core.contract import AgentContract
from ..core.schemas import Verdict

MIN_GIF_SECONDS = 3.0


class VerifierAgent(Agent):
    """Decide si el GIF grabado es apto o necesita reparación.

    Criterios deterministas — nada de LLM juzgando a ojo:
    - la verificación ffprobe debe ser ok (existe, dura >1s, pesa >20KB)
    - ningún paso de la coreografía falló
    - duración mínima: un GIF más corto que MIN_GIF_SECONDS significa que
      la demo no se vio.
    """

    contract = AgentContract(
        id="verifier",
        name="Verifier",
        description="Verifica el artefacto con ffprobe y criterios duros",
        reads=("gif",),
        writes="verdict",
        output_model=Verdict,
        allowed_tools=("verify_media",),
    )

    async def execute(self, ctx: dict[str, Any]) -> Verdict:
        gif = ctx["gif"]
        verification = gif.get("verification") or {}
        failed_steps = int(gif.get("failed_steps") or 0)
        duration = float(verification.get("duration") or 0)

        if failed_steps > 0:
            return Verdict(
                ok=False,
                target=gif.get("path", ""),
                reason=f"{failed_steps} paso(s) de la coreografía fallaron",
                should_repair=True,
            )
        if not verification.get("ok"):
            return Verdict(
                ok=False,
                target=gif.get("path", ""),
                reason=f"verificación ffprobe falló: duration={duration}, size={verification.get('size')}",
                should_repair=True,
            )
        if duration < MIN_GIF_SECONDS:
            return Verdict(
                ok=False,
                target=gif.get("path", ""),
                reason=f"GIF demasiado corto ({duration}s < {MIN_GIF_SECONDS}s)",
                should_repair=True,
            )
        return Verdict(ok=True, target=gif.get("path", ""))
