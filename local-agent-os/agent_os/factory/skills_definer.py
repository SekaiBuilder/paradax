from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..core.agent import LLMAgent
from ..core.contract import AgentContract
from ..core.models import resolve_model
from .tool_catalog import catalog_text, has_tool

PROMPT_PATH = Path(__file__).parent / "prompts" / "skills_definer.md"


class AgentBrief(BaseModel):
    agent_name: str
    need: str
    skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)


class TeamBriefs(BaseModel):
    briefs: list[AgentBrief] = Field(min_length=1)


class SkillsDefinerAgent(LLMAgent):
    """Sub-agente 2 del Project Manager: define, por agente del equipo, las
    habilidades (skills + tools) y redacta el encargo para el Constructor."""

    contract = AgentContract(
        id="skills_definer",
        name="Definidor de habilidades",
        description="Define las skills/tools de cada agente y prepara el encargo al Constructor",
        reads=("goal", "team_plan", "skills_catalog", "model"),
        writes="briefs",
        output_model=TeamBriefs,
        uses_llm=True,
        max_retries=2,
    )

    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    async def execute(self, ctx: dict[str, Any]) -> TeamBriefs:
        model, _ = resolve_model(self.contract.id, ctx["model"])
        team = ctx["team_plan"].get("agents", []) if isinstance(ctx["team_plan"], dict) else []
        team_text = "\n".join(f"- {a.get('name')}: {a.get('role')}" for a in team) or "(equipo vacío)"
        user = f"""Objetivo del proyecto:
{ctx['goal']}

Equipo ya nombrado (un brief por cada uno):
{team_text}

Skills disponibles (elige por id, no inventes):
{_skills_text(ctx['skills_catalog'])}

Herramientas disponibles:
{catalog_text()}

Devuelve SOLO el JSON con un brief por agente."""
        briefs, _source = await self.ask_validated(model, user, ctx)
        return briefs

    def postprocess(self, raw: dict, ctx: dict[str, Any]) -> dict:
        if isinstance(raw, dict) and not isinstance(raw.get("briefs"), list):
            raw["briefs"] = []
        return raw

    def semantic_check(self, validated: BaseModel, ctx: dict[str, Any]) -> str:
        briefs: TeamBriefs = validated  # type: ignore[assignment]
        known_skills = {s["id"] for s in (ctx.get("skills_catalog") or []) if isinstance(s, dict) and "id" in s}
        problems: list[str] = []
        for b in briefs.briefs:
            bad_skills = [s for s in b.skills if s not in known_skills]
            if bad_skills:
                problems.append(f"{b.agent_name}: skills inexistentes {bad_skills}")
            bad_tools = [t for t in b.tools if not has_tool(t)]
            if bad_tools:
                problems.append(f"{b.agent_name}: tools inexistentes {bad_tools}")
        return " · ".join(problems)


def _skills_text(catalog: list[dict[str, Any]]) -> str:
    if not catalog:
        return "(ninguna)"
    return "\n".join(
        f"- {s.get('id')}: {s.get('name')} — {s.get('description', '')}" for s in catalog
    )
