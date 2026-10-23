from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..core.agent import LLMAgent
from ..core.contract import AgentContract
from ..core.models import resolve_model

PROMPT_PATH = Path(__file__).parent / "prompts" / "team_planner.md"
MAX_TEAM = 6


class PlannedAgent(BaseModel):
    name: str
    role: str


class TeamPlan(BaseModel):
    reasoning_summary: str = ""
    agents: list[PlannedAgent] = Field(min_length=1)


class TeamPlannerAgent(LLMAgent):
    """Sub-agente 1 del Project Manager: estudia cuántos agentes hacen falta y
    los nombra. No diseña cada agente — solo el equipo (nombre + rol)."""

    contract = AgentContract(
        id="team_planner",
        name="Planificador de equipo",
        description="Decide cuántos agentes necesita el proyecto y los nombra",
        reads=("goal", "model"),
        writes="team_plan",
        output_model=TeamPlan,
        uses_llm=True,
        max_retries=2,
    )

    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    async def execute(self, ctx: dict[str, Any]) -> TeamPlan:
        model, _ = resolve_model(self.contract.id, ctx["model"])
        user = f"Objetivo del proyecto:\n{ctx['goal']}\n\nDevuelve SOLO el JSON del equipo."
        plan, _source = await self.ask_validated(model, user, ctx)
        return plan

    def postprocess(self, raw: dict, ctx: dict[str, Any]) -> dict:
        if isinstance(raw, dict) and not isinstance(raw.get("agents"), list):
            raw["agents"] = []
        return raw

    def semantic_check(self, validated: BaseModel, ctx: dict[str, Any]) -> str:
        plan: TeamPlan = validated  # type: ignore[assignment]
        if len(plan.agents) > MAX_TEAM:
            return f"demasiados agentes ({len(plan.agents)}); el máximo es {MAX_TEAM}. Reduce el equipo."
        return ""
