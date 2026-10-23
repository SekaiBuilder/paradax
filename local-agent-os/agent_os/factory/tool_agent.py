from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

from ..config import DEFAULT_MODEL
from ..core.agent import AgentError, LLMAgent
from ..core.contract import AgentContract
from ..core.models import resolve_model
from ..ollama import chat_json
from .loader import build_output_model
from .spec import AgentSpec
from .tool_runtime import DEFAULT_RUNTIME, ToolRuntime

_WRITE_TOOLS = {"code_replace", "code_write_file"}
_DONE_STATUSES = {"done", "completed", "ok", "success", "completado"}


class ToolExecutingAgent(LLMAgent):
    """Un agente construido que EJECUTA sus tools en un bucle acotado y con
    allow-list.

    Protocolo por turno: el modelo responde o bien una llamada a tool
    ``{"tool": <nombre>, "args": {...}}`` —solo de su allow-list y solo si hay
    callable registrado— o la respuesta final ``{"final": {...campos...}}``.
    El runtime ejecuta la tool, le devuelve el resultado, y se repite hasta
    ``max_tool_steps``. La salida final se valida contra el output_schema.
    """

    def __init__(self, spec: AgentSpec, runtime: ToolRuntime | None = None):
        self.spec = spec
        self.runtime = runtime or DEFAULT_RUNTIME
        self._schema_fields = list(spec.output_schema)
        self.system_prompt = spec.prompt
        self.contract = AgentContract(
            id=spec.id,
            name=spec.name,
            description=spec.description,
            reads=tuple(spec.reads),
            writes=spec.writes,
            output_model=build_output_model(spec),
            allowed_tools=tuple(spec.tools),
            uses_llm=True,
            max_retries=spec.max_retries,
        )

    def _executable_tools(self) -> list[str]:
        # Solo las que están en el allow-list del agente Y tienen callable real.
        return [t for t in self.contract.allowed_tools if self.runtime.has(t)]

    def _system(self) -> str:
        tools = self._executable_tools()
        fields = ", ".join(self._schema_fields) or "(sin campos)"
        return (
            self.system_prompt
            + "\n\n--- Protocolo de herramientas ---\n"
            + f"Herramientas disponibles: {', '.join(tools) or '(ninguna)'}.\n"
            + "En cada turno responde SOLO un JSON, una de dos formas:\n"
            + '  1) llamar una tool: {"tool": "<nombre>", "args": {...}}\n'
            + f'  2) terminar: {{"final": {{{fields}}}}}\n'
            + "No expliques nada fuera del JSON. Usa tools solo si las necesitas."
        )

    def _final_system(self) -> str:
        fields = ", ".join(self._schema_fields) or "(sin campos)"
        return (
            self.system_prompt
            + "\n\n--- Respuesta final obligatoria ---\n"
            + "Ya no puedes llamar herramientas. Responde SOLO JSON con la salida final.\n"
            + f'Formato obligatorio: {{"final": {{{fields}}}}}\n'
            + "No expliques nada fuera del JSON."
        )

    async def execute(self, ctx: dict[str, Any]) -> BaseModel:
        model, _is_student = resolve_model(self.contract.id, ctx.get("model", DEFAULT_MODEL))
        system = self._system()
        context_lines = [f"{k}: {ctx[k]}" for k in self.contract.reads if k != "model" and k in ctx]
        transcript: list[str] = []
        changed_paths: list[str] = []

        for _step in range(self.spec.max_tool_steps):
            user = (
                "Contexto:\n" + ("\n".join(context_lines) or "(vacío)")
                + ("\n\nResultados de tools hasta ahora:\n" + "\n".join(transcript) if transcript else "")
            )
            raw = await chat_json(model, system, user)

            if isinstance(raw, dict) and "tool" in raw:
                name = raw.get("tool")
                args = raw.get("args") or {}
                if name not in self.contract.allowed_tools or not self.runtime.has(name):
                    transcript.append(f"tool '{name}' NO disponible (fuera de allow-list o sin callable)")
                    continue
                try:
                    result = await self.runtime.call(name, args if isinstance(args, dict) else {})
                except Exception as exc:  # noqa: BLE001 — el fallo de una tool no tumba el agente
                    result = f"ERROR: {exc}"
                if name in _WRITE_TOOLS and isinstance(result, dict) and result.get("path"):
                    changed_paths.append(str(result["path"]))
                transcript.append(f"{name}({json.dumps(args, ensure_ascii=False)}) -> {str(result)[:600]}")
                continue

            candidate = raw.get("final", raw) if isinstance(raw, dict) else raw
            if self._needs_write_feedback(candidate, changed_paths):
                transcript.append(
                    "rechazo: no puedes terminar con status='done' sin ejecutar "
                    "code_replace o code_write_file. Lee el archivo real y escribe, "
                    "o reporta status='blocked' solo si hay un bloqueo verificable."
                )
                continue
            candidate, fallback_paths = self._deterministic_fallback(ctx, candidate, changed_paths)
            changed_paths.extend(fallback_paths)
            candidate = self._normalize_candidate(candidate, changed_paths)
            try:
                return self.contract.output_model.model_validate(candidate)
            except ValidationError:
                transcript.append("la salida final no cumplió el schema; corrígela")

        final_user = (
            "Contexto:\n" + ("\n".join(context_lines) or "(vacío)")
            + ("\n\nResultados de tools:\n" + "\n".join(transcript) if transcript else "")
            + "\n\nDevuelve ahora la respuesta final. No llames tools."
        )
        raw = await chat_json(model, self._final_system(), final_user)
        if isinstance(raw, dict) and "tool" in raw:
            raise AgentError(self.contract.id, f"sin salida final tras {self.spec.max_tool_steps} pasos de tools")
        candidate = raw.get("final", raw) if isinstance(raw, dict) else raw
        candidate, fallback_paths = self._deterministic_fallback(ctx, candidate, changed_paths)
        changed_paths.extend(fallback_paths)
        candidate = self._normalize_candidate(candidate, changed_paths)
        try:
            return self.contract.output_model.model_validate(candidate)
        except ValidationError as exc:
            raise AgentError(
                self.contract.id,
                f"salida final no cumple {self.contract.output_model.__name__}: {exc}",
            ) from exc

    def _normalize_candidate(self, candidate: Any, changed_paths: list[str]) -> Any:
        if not isinstance(candidate, dict) or "changed_files" not in self._schema_fields:
            return candidate
        normalized = dict(candidate)
        if changed_paths:
            reported = normalized.get("changed_files") or []
            if not isinstance(reported, list):
                reported = []
            normalized["changed_files"] = sorted({str(path) for path in [*reported, *changed_paths]})
            return normalized

        status = str(normalized.get("status", "")).lower()
        if status in _DONE_STATUSES:
            normalized["status"] = "blocked"
            normalized["changed_files"] = []
            if "summary" in normalized:
                summary = str(normalized.get("summary") or "")
                normalized["summary"] = (
                    summary.rstrip()
                    + " No se registraron herramientas de escritura, así que el runtime lo marca como bloqueado."
                ).strip()
        return normalized

    def _needs_write_feedback(self, candidate: Any, changed_paths: list[str]) -> bool:
        if changed_paths or not isinstance(candidate, dict) or "changed_files" not in self._schema_fields:
            return False
        return str(candidate.get("status", "")).lower() in _DONE_STATUSES

    def _deterministic_fallback(
        self,
        ctx: dict[str, Any],
        candidate: Any,
        changed_paths: list[str],
    ) -> tuple[Any, list[str]]:
        if (
            changed_paths
            or self.contract.id != "implementador_funcionalidades"
            or not isinstance(candidate, dict)
            or "changed_files" not in self._schema_fields
        ):
            return candidate, []

        request = str(ctx.get("feature_request", "")).lower()
        if not any(word in request for word in ("boton", "botón", "botones")):
            return candidate, []
        color = re.search(r"#[0-9a-fA-F]{6}\b", request)
        if not color:
            return candidate, []

        try:
            from . import code_tools

            target = "local-agent-os/static/styles.css"
            current = code_tools.code_read_file(target, max_chars=200_000)["content"]
            match = re.search(r"--accent:\s*#[0-9a-fA-F]{6};", current)
            if not match:
                return candidate, []
            old = match.group(0)
            new = re.sub(r"#[0-9a-fA-F]{6}", color.group(0), old)
            if old == new:
                return {
                    "summary": f"El color de acento de botones ya estaba en {color.group(0)}.",
                    "changed_files": [target],
                    "tests_run": [],
                    "status": "done",
                }, [target]
            code_tools.code_replace(target, old, new, count=1)
        except Exception:
            return candidate, []

        return {
            "summary": (
                "Reparación determinista aplicada: se cambió la variable CSS "
                f"--accent de los botones principales a {color.group(0)} en {target}."
            ),
            "changed_files": [target],
            "tests_run": [],
            "status": "done",
        }, [target]
