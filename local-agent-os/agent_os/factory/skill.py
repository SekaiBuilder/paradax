from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# Una skill es la unidad reutilizable que el Constructor compone para fabricar
# un agente. No es solo una herramienta: puede ser un fragmento de prompt, un
# set de ejemplos few-shot, casos de eval, o un schema de salida. El Skill
# Master guarda muchas; el Constructor pide las relevantes a un proyecto.
SkillKind = Literal["tool", "prompt", "example", "eval", "schema", "capability"]


class Skill(BaseModel):
    """Una capacidad reutilizable que vive en el Skill Master.

    Solo `id`, `name`, `kind` y `description` son obligatorios; el resto son
    piezas opcionales que el Constructor recombina. Los campos vacíos no se
    serializan (ver `skill_wire`), así que una skill mínima pesa muy poco.
    """

    id: str
    name: str
    kind: SkillKind
    description: str = ""

    tags: list[str] = Field(default_factory=list)        # p. ej. ["web", "selectores"]
    tools: list[str] = Field(default_factory=list)        # nombres de tools del catálogo que ata
    prompt: str = ""                                       # fragmento de instrucciones
    examples: list[dict[str, Any]] = Field(default_factory=list)  # few-shot {input, output}
    evals: list[dict[str, Any]] = Field(default_factory=list)     # casos {input, expect}
    output_schema: dict[str, Any] = Field(default_factory=dict)   # gramática campo→tipo

    created_by: str = "human"   # human | constructor | ghost | entrenador
    version: int = 1

    @field_validator("id")
    @classmethod
    def _ascii_id(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", v):
            raise ValueError("id debe ser ascii simple (minúsculas, dígitos, _.-)")
        return v

    def to_wire(self) -> dict[str, Any]:
        """Forma compacta (short-keys, sin vacíos). Ver `skill_wire.encode_skill`."""
        from .skill_wire import encode_skill
        return encode_skill(self.model_dump())

    @classmethod
    def from_wire(cls, compact: dict[str, Any]) -> "Skill":
        from .skill_wire import decode_skill
        return cls.model_validate(decode_skill(compact))
