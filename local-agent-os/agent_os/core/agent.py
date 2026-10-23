from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ValidationError

from ..ollama import chat_json
from .contract import AgentContract


# Sumidero opcional de ejemplos de entrenamiento: callable(agent_id, system,
# user, output_dict, source). Lo activa el entrenamiento nocturno; en
# producción es None y no cuesta nada.
CAPTURE_SINK = None

# Sumidero de salidas CRUDAS (antes de validar, cada intento):
# callable(agent_id, model, user, raw_dict, attempt). Lo usa el detector de
# reacciones inesperadas: lo raro suele estar justo en lo que no pasa el schema.
RAW_SINK = None


def strict_schema_agents() -> set[str]:
    """Agentes con decodificación restringida al schema de salida:
    PARADAX_STRICT_SCHEMA="team_planner,skills_definer". Vacío = ninguno."""
    return {a.strip() for a in os.getenv("PARADAX_STRICT_SCHEMA", "").split(",") if a.strip()}


class AgentError(RuntimeError):
    def __init__(self, agent_id: str, message: str):
        self.agent_id = agent_id
        super().__init__(f"[{agent_id}] {message}")


class Agent(ABC):
    """Agente con contrato. Recibe SOLO las claves declaradas en `reads` y
    devuelve una instancia validada de `contract.output_model`."""

    contract: AgentContract

    async def run(self, ctx: dict[str, Any]) -> BaseModel:
        missing = [k for k in self.contract.reads if k not in ctx]
        if missing:
            raise AgentError(self.contract.id, f"faltan claves de contexto: {missing}")
        limited = {k: ctx[k] for k in self.contract.reads}
        # "model" es METADATO del run (qué LLM usar), no un dato del contrato:
        # atraviesa el filtro siempre. Sin esto, cualquier agente sin "model"
        # en sus reads caía al DEFAULT_MODEL e ignoraba el modelo elegido.
        if "model" in ctx:
            limited.setdefault("model", ctx["model"])
        result = await self.execute(limited)
        if not isinstance(result, self.contract.output_model):
            try:
                result = self.contract.output_model.model_validate(result)
            except ValidationError as exc:
                raise AgentError(
                    self.contract.id, f"salida no cumple {self.contract.output_model.__name__}: {exc}"
                ) from exc
        return result

    @abstractmethod
    async def execute(self, ctx: dict[str, Any]) -> BaseModel | dict:
        ...


class LLMAgent(Agent):
    """Agente respaldado por LLM con formato de salida obligatorio.

    Pide JSON al modelo, valida contra el schema del contrato y reintenta
    `max_retries` veces devolviéndole al modelo el error de validación.
    Si agota reintentos delega en `fallback()` — que cada agente define o no.
    """

    system_prompt: str = ""

    async def ask_validated(
        self, model: str, user_prompt: str, ctx: dict[str, Any], system: str | None = None
    ) -> tuple[BaseModel, str]:
        """Devuelve (salida_validada, fuente). Fuente: 'model', 'model_retry_N'
        o 'fallback:<motivo>'. Nunca un fallback silencioso.

        `system` permite usar un prompt distinto al de producción — p. ej. el
        prompt compacto del alumno fine-tuneado. Si es None, usa system_prompt.
        """
        system_prompt = system if system is not None else self.system_prompt
        last_error = ""
        prompt = user_prompt
        # Decodificación restringida al schema, solo si se activa para este agente:
        # en modelos pequeños puede costar precisión, hay que medirlo antes.
        strict = self.contract.id in strict_schema_agents()
        schema_kw: dict[str, Any] = {"schema": self.contract.output_model.model_json_schema()} if strict else {}
        for attempt in range(self.contract.max_retries + 1):
            try:
                raw = await chat_json(model, system_prompt, prompt, **schema_kw)
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                break
            if RAW_SINK is not None:
                try:
                    RAW_SINK(self.contract.id, model, user_prompt, raw, attempt)
                except Exception:
                    pass
            candidate = self.postprocess(raw, ctx)
            try:
                validated = self.contract.output_model.model_validate(candidate)
            except ValidationError as exc:
                last_error = str(exc)
                prompt = (
                    user_prompt
                    + "\n\nTu respuesta anterior NO cumplió el formato. Errores:\n"
                    + last_error[:1200]
                    + "\nDevuelve SOLO el JSON corregido."
                )
                continue
            extra = self.semantic_check(validated, ctx)
            if extra:
                last_error = extra
                prompt = (
                    user_prompt
                    + "\n\nTu respuesta anterior fue rechazada:\n"
                    + extra[:1200]
                    + "\nDevuelve SOLO el JSON corregido."
                )
                continue
            source = "model" if attempt == 0 else f"model_retry_{attempt}"
            if CAPTURE_SINK is not None:
                try:
                    # Se guarda el prompt ORIGINAL: el alumno aprende a acertar
                    # a la primera, no a corregirse.
                    CAPTURE_SINK(self.contract.id, system_prompt, user_prompt,
                                 validated.model_dump(mode="json"), source)
                except Exception:
                    pass  # capturar nunca debe romper un run
            return validated, source

        fb = self.fallback(ctx, last_error)
        if fb is None:
            raise AgentError(self.contract.id, f"sin salida válida: {last_error[:500]}")
        return fb, f"fallback:{last_error[:300] or 'sin_motivo'}"

    def postprocess(self, raw: dict, ctx: dict[str, Any]) -> dict:
        """Normalización previa a validar (limpiar acciones, nombres…)."""
        return raw

    def semantic_check(self, validated: BaseModel, ctx: dict[str, Any]) -> str:
        """Validación más allá del schema (p. ej. selectores permitidos).
        Devuelve '' si ok, o el motivo de rechazo para reintentar."""
        return ""

    def fallback(self, ctx: dict[str, Any], reason: str) -> BaseModel | None:
        """Plan determinista de emergencia; None = no hay fallback."""
        return None


def compact(data: Any, limit: int = 800) -> str:
    """Resumen JSON corto para logs/eventos."""
    text = json.dumps(data, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "…"
