from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..core.agent import LLMAgent
from ..core.contract import AgentContract
from ..core.models import resolve_model
from .spec import TYPE_VOCAB, AgentSpec
from .tool_catalog import catalog_text, has_tool

PROMPT_PATH = Path(__file__).parent / "prompts" / "constructor.md"


def _language_of(text: str) -> str:
    """Idioma en que el usuario pidió el agente: el spec se escribe en ese idioma."""
    t = f" {text.lower()} "
    spanish = sum(w in t for w in (" que ", " de ", " un ", " una ", " para ", " los ", " las ", " del ", " con ", " el ", " la "))
    if any(c in t for c in "áéíóúñ¿¡") or spanish >= 2:
        return "español"
    english = sum(w in t for w in (" the ", " that ", " an ", " a ", " of ", " for ", " and ", " to ", " with "))
    return "inglés" if english >= 2 else "el mismo idioma que la necesidad del proyecto"


class ConstructorAgent(LLMAgent):
    """Pilar 1: convierte la necesidad de un proyecto en un spec de agente válido.

    Tres barreras, como cualquier agente del sistema:
    1. Schema pydantic (AgentSpec) — tipos del output_schema dentro de la gramática.
    2. Normalización (postprocess): listas garantizadas, defaults.
    3. Chequeo semántico: id libre, tools del catálogo, skills que existen,
       output_schema no vacío para un agente LLM. Si falla, reintenta con el motivo.
    """

    contract = AgentContract(
        id="constructor",
        name="Constructor",
        description="Fabrica agentes nuevos como spec validado, componiendo skills y tools existentes",
        reads=("request", "skills_catalog", "taken_ids", "model"),
        writes="spec",
        output_model=AgentSpec,
        uses_llm=True,
        max_retries=2,
    )

    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    async def execute(self, ctx: dict[str, Any]) -> AgentSpec:
        model, _is_student = resolve_model(self.contract.id, ctx["model"])
        user = f"""Necesidad del proyecto: {ctx["request"]}

Skills disponibles (elige por id, no inventes):
{_skills_text(ctx["skills_catalog"])}

Herramientas disponibles (catálogo):
{catalog_text()}

Tipos permitidos para output_schema: {", ".join(sorted(TYPE_VOCAB))}

Escribe name, description y prompt en {_language_of(ctx["request"])}.
Devuelve SOLO el JSON del spec del agente."""
        spec, source = await self.ask_validated(model, user, ctx)
        spec.created_by = "constructor"
        if source != "model":
            spec.version = 1
        return spec

    # ── Barrera 2: normalización ────────────────────────────────────────────
    def postprocess(self, raw: dict, ctx: dict[str, Any]) -> dict:
        if not isinstance(raw, dict):
            return raw
        raw.setdefault("uses_llm", True)
        for key in ("reads", "skills", "tools", "evals"):
            if key in raw and not isinstance(raw[key], list):
                raw[key] = [raw[key]] if raw[key] else []
        if "output_schema" in raw and not isinstance(raw["output_schema"], dict):
            raw["output_schema"] = {}
        return raw

    # ── Barrera 3: existe lo que ata, id libre, schema utilizable ───────────
    def semantic_check(self, validated: BaseModel, ctx: dict[str, Any]) -> str:
        spec: AgentSpec = validated  # type: ignore[assignment]
        problems: list[str] = []

        taken = set(ctx.get("taken_ids") or [])
        if spec.id in taken:
            problems.append(f"el id '{spec.id}' ya existe; elige otro")

        bad_tools = [t for t in spec.tools if not has_tool(t)]
        if bad_tools:
            problems.append(f"tools que no existen en el catálogo: {bad_tools}")

        known_skills = {s["id"] for s in (ctx.get("skills_catalog") or []) if isinstance(s, dict) and "id" in s}
        bad_skills = [s for s in spec.skills if s not in known_skills]
        if bad_skills:
            problems.append(f"skills que no existen en el Skill Master: {bad_skills}")

        if not spec.writes:
            problems.append("falta 'writes' (clave de salida)")
        if spec.uses_llm and not spec.output_schema:
            problems.append("un agente LLM necesita 'output_schema' no vacío")
        from .tool_runtime import DEFAULT_RUNTIME
        runnable = [t for t in spec.tools if DEFAULT_RUNTIME.has(t)]
        if runnable and not spec.uses_tools:
            problems.append(
                f"declaras las tools {runnable} pero uses_tools=false, así que nunca se ejecutarían: "
                "pon uses_tools=true (o quita las tools si el agente solo razona)"
            )
        if spec.uses_llm and len(spec.prompt.strip()) < MIN_PROMPT_CHARS:
            problems.append(
                f"prompt demasiado corto ({len(spec.prompt.strip())} caracteres, mínimo {MIN_PROMPT_CHARS}): "
                "describe entrada, tarea, criterios y formato de salida"
            )

        return " · ".join(problems)


MIN_PROMPT_CHARS = 150  # un prompt de una frase pasa el schema pero no especifica nada


def _skills_text(catalog: list[dict[str, Any]]) -> str:
    if not catalog:
        return "(ninguna — el Constructor deberá pedir una nueva vía el fantasma)"
    lines = []
    for s in catalog:
        tags = ", ".join(s.get("tags", [])) if isinstance(s.get("tags"), list) else ""
        lines.append(f"- {s.get('id')}: {s.get('name')} — {s.get('description', '')} [{tags}]")
    return "\n".join(lines)
