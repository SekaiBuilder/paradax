from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, create_model

from ..config import DATA_DIR, DEFAULT_MODEL
from ..core.agent import LLMAgent
from ..core.contract import AgentContract
from ..core.models import resolve_model
from .spec import TYPE_VOCAB, AgentSpec

SPECS_DIR = DATA_DIR / "specs"
_IDENT = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")


def build_output_model(spec: AgentSpec) -> type[BaseModel]:
    """Compila el `output_schema` (datos) a un modelo pydantic real en runtime."""
    fields: dict[str, Any] = {}
    for name, token in spec.output_schema.items():
        if not _IDENT.fullmatch(name):
            raise ValueError(f"campo de salida no válido como identificador: {name!r}")
        if token not in TYPE_VOCAB:
            raise ValueError(f"tipo fuera de la gramática: {token!r}")
        fields[name] = (TYPE_VOCAB[token], ...)
    model_name = "".join(p.capitalize() for p in spec.id.split("_")) + "Output"
    return create_model(model_name, **fields)  # type: ignore[call-overload]


class ConstructedAgent(LLMAgent):
    """Un agente fabricado desde un spec, compilado en runtime.

    v1: generación validada — recibe sus `reads`, pide JSON al modelo y valida
    contra el output_model construido. Las mismas barreras de cualquier LLMAgent.
    """

    def __init__(self, spec: AgentSpec):
        self.spec = spec
        self.system_prompt = spec.prompt
        self._schema_fields = list(spec.output_schema)
        self.contract = AgentContract(
            id=spec.id,
            name=spec.name,
            description=spec.description,
            reads=tuple(spec.reads),
            writes=spec.writes,
            output_model=build_output_model(spec),
            allowed_tools=tuple(spec.tools),
            uses_llm=spec.uses_llm,
            max_retries=spec.max_retries,
        )

    def _compact(self) -> bool:
        """El protocolo glyph solo se usa si el spec lo activó (alumno destilado)."""
        return bool(getattr(self.spec, "compact_protocol", False))

    def build_user_prompt(self, ctx: dict[str, Any]) -> str:
        """El user prompt exacto que ve el agente. El distiller reproduce este
        mismo formato para que el alumno no vea entrada fuera de distribución.

        En modo compacto se piden claves glyph: menos tokens generados por
        llamada (el alumno fue entrenado para emitirlas nativas)."""
        lines = [f"{k}: {ctx[k]}" for k in self.contract.reads if k != "model" and k in ctx]
        if self._compact():
            from ..core.glyph import legend
            return (
                "Contexto:\n" + ("\n".join(lines) or "(vacío)")
                + f"\n\nDevuelve SOLO JSON con claves compactas: {legend(self._schema_fields)}."
            )
        fields = ", ".join(self._schema_fields) or "(sin campos)"
        return (
            "Contexto:\n" + ("\n".join(lines) or "(vacío)")
            + f"\n\nDevuelve SOLO JSON con exactamente estos campos: {fields}."
        )

    def postprocess(self, raw: Any, ctx: dict[str, Any]) -> Any:
        """En modo compacto, expande las claves glyph al schema real antes de
        validar contra el contrato."""
        if self._compact() and isinstance(raw, dict):
            from ..core.glyph import expand
            return expand(raw, self._schema_fields)
        return raw

    async def execute(self, ctx: dict[str, Any]) -> BaseModel:
        model, _is_student = resolve_model(self.contract.id, ctx.get("model", DEFAULT_MODEL))
        out, source = await self.ask_validated(model, self.build_user_prompt(ctx), ctx)
        # Señal de calidad del turno para el Proposer (Multi-Agent Evolve):
        # "model" = acertó a la primera; "model_retry_N"/"fallback" = tarea dura.
        self._last_source = source
        return out


def make_agent(spec: AgentSpec, runtime: Any | None = None) -> LLMAgent:
    """Elige la clase de agente según el spec: ejecutor de tools o generación
    validada. Import perezoso de ToolExecutingAgent para evitar ciclo."""
    if spec.uses_tools and spec.tools:
        from .tool_agent import ToolExecutingAgent
        return ToolExecutingAgent(spec, runtime=runtime)
    return ConstructedAgent(spec)


class DynamicRegistry:
    """Registro de agentes construidos, vive junto al REGISTRY estático.

    El control center dibuja la unión de ambos, así que un agente registrado
    aquí aparece solo en el grafo.
    """

    def __init__(self, root: Path | None = None):
        self.root = root or SPECS_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        self._agents: dict[str, LLMAgent] = {}

    def register(self, spec: AgentSpec, persist: bool = True) -> LLMAgent:
        agent = make_agent(spec)  # construir valida que compila
        self._agents[spec.id] = agent
        if persist:
            (self.root / f"{spec.id}.json").write_text(
                json.dumps(spec.model_dump(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return agent

    def unregister(self, agent_id: str) -> bool:
        existed = self._agents.pop(agent_id, None) is not None
        path = self.root / f"{agent_id}.json"
        if path.exists():
            path.unlink()
        return existed

    def get(self, agent_id: str) -> LLMAgent | None:
        return self._agents.get(agent_id)

    def all(self) -> list[LLMAgent]:
        return list(self._agents.values())

    def ids(self) -> list[str]:
        return list(self._agents)

    def load_all(self) -> int:
        """Carga los specs persistidos al arrancar. Ignora los que no compilan."""
        count = 0
        for path in sorted(self.root.glob("*.json")):
            try:
                spec = AgentSpec.model_validate(json.loads(path.read_text(encoding="utf-8")))
                self.register(spec, persist=False)
                count += 1
            except Exception:
                continue
        return count


# Instancia por defecto compartida con el servidor.
DYNAMIC = DynamicRegistry()
