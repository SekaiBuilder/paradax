from __future__ import annotations

import re

from pydantic import BaseModel

from .spec import TYPE_VOCAB, AgentSpec
from .tool_catalog import has_tool

_IDENT = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*")


class AuditReport(BaseModel):
    ok: bool
    issues: list[str] = []     # bloquean
    warnings: list[str] = []   # no bloquean, solo avisan


class Auditor:
    """Revisa lo que el Constructor crea — deterministamente, como el Verifier.

    El Constructor ya se autocomprueba; el Auditor es defensa en profundidad:
    un segundo par de ojos antes de que el spec llegue al Validador. No usa LLM.
    """

    def audit(self, spec: AgentSpec, taken_ids: list[str] | None = None) -> AuditReport:
        issues: list[str] = []
        warnings: list[str] = []
        taken = set(taken_ids or [])

        if spec.id in taken:
            issues.append(f"id '{spec.id}' ya existe")
        if not spec.writes:
            issues.append("falta 'writes'")
        if not spec.reads:
            warnings.append("el agente no declara 'reads' (no leerá contexto)")

        # output_schema: tipos válidos + nombres de campo usables como identificadores
        if spec.uses_llm and not spec.output_schema:
            issues.append("agente LLM sin 'output_schema'")
        for field, token in spec.output_schema.items():
            if token not in TYPE_VOCAB:
                issues.append(f"tipo no permitido en '{field}': {token}")
            if not _IDENT.fullmatch(field):
                issues.append(f"nombre de campo no válido como identificador: '{field}'")

        bad_tools = [t for t in spec.tools if not has_tool(t)]
        if bad_tools:
            issues.append(f"tools fuera del catálogo: {bad_tools}")

        from .tool_runtime import DEFAULT_RUNTIME
        runnable = [t for t in spec.tools if DEFAULT_RUNTIME.has(t)]
        if runnable and not spec.uses_tools:
            issues.append(
                f"declara tools ejecutables {runnable} pero uses_tools=false: nunca las ejecutará "
                "(poner uses_tools=true, o quitar las tools si solo razona)"
            )

        if spec.uses_tools:
            not_exec = [t for t in spec.tools if not DEFAULT_RUNTIME.has(t)]
            if not_exec:
                warnings.append(
                    f"tools sin callable ejecutable (solo metadata): {not_exec} — "
                    "el agente recibirá 'tool no disponible' hasta que se wireen a mano"
                )

        if spec.uses_llm and len(spec.prompt.strip()) < 20:
            issues.append("el prompt del agente es demasiado corto para ser útil")

        if not spec.evals:
            warnings.append("sin evals: no se podrá medir ni destilar este agente")
        else:
            for i, ev in enumerate(spec.evals):
                if not isinstance(ev, dict) or "input" not in ev:
                    issues.append(f"eval #{i} mal formado (falta 'input')")

        return AuditReport(ok=not issues, issues=issues, warnings=warnings)
