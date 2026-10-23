from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field, field_validator

# Gramática del schema de salida: tokens de tipo → tipo Python para construir
# el output_model con pydantic.create_model en runtime (ver loader). Es
# deliberadamente pequeña: el Constructor elige de aquí, no inventa tipos.
TYPE_VOCAB: dict[str, Any] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
    "list[str]": list[str],
    "list[int]": list[int],
    "list[dict]": list[dict],
}


class AgentSpec(BaseModel):
    """La salida obligatoria del Constructor: un agente descrito como DATOS.

    No es código. El loader lo compila a un `LLMAgent` en runtime. Las mismas
    barreras que cualquier agente: schema (este modelo), chequeo semántico
    (ids/tools/skills que existen, tipos válidos) y reintento con feedback.
    """

    id: str
    name: str
    description: str = ""

    reads: list[str] = Field(default_factory=list)   # claves de contexto que recibe
    writes: str                                       # clave bajo la que escribe su salida
    output_schema: dict[str, str] = Field(default_factory=dict)  # campo → token de tipo

    skills: list[str] = Field(default_factory=list)   # ids de skills del Skill Master
    tools: list[str] = Field(default_factory=list)    # nombres de tools del catálogo
    prompt: str = ""                                  # system prompt del agente

    uses_llm: bool = True
    uses_tools: bool = False          # si True, ejecuta sus tools en un bucle acotado
    max_retries: int = 1
    max_tool_steps: int = 4           # tope de iteraciones del bucle de tools
    # Protocolo compacto (glyph): lo activa el destilador al entrenar un alumno.
    # El especialista aprende a hablar prompt corto + salida glyph → mucho menos
    # cómputo por llamada. El maestro genérico jamás lo usa (sería poco fiable).
    compact_protocol: bool = False
    evals: list[dict[str, Any]] = Field(default_factory=list)  # {input:{...}, expect:{...}}

    created_by: str = "constructor"
    project: str = ""                 # id del proyecto al que pertenece (si lo creó un PM)
    tier: str = ""                    # "secondary" (decide) | "tertiary" (específico); vacío = derivado
    version: int = 1

    @field_validator("id")
    @classmethod
    def _ascii_id(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", v):
            raise ValueError("id de agente debe ser ascii simple (minúsculas, dígitos, _)")
        return v

    @field_validator("output_schema")
    @classmethod
    def _known_types(cls, v: dict[str, str]) -> dict[str, str]:
        bad = {f: t for f, t in v.items() if t not in TYPE_VOCAB}
        if bad:
            raise ValueError(
                f"tipos fuera de la gramática: {bad}. Permitidos: {sorted(TYPE_VOCAB)}"
            )
        return v


def effective_tier(spec: AgentSpec) -> str:
    """Jerarquía de agentes construidos:
    - 'secondary' (secundario): puede DECIDIR — ejecuta herramientas en bucle.
    - 'tertiary' (terciario): capacidad 100% específica — generación validada.
    Los 'principales' (Constructor, Entrenador, Orquestador, PM) son de sistema,
    no construidos. Si el spec no fija tier, se deriva de uses_tools."""
    if spec.tier:
        return spec.tier
    return "secondary" if spec.uses_tools else "tertiary"
