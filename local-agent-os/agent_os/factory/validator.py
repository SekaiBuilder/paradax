from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .auditor import AuditReport, Auditor
from .loader import ConstructedAgent, DynamicRegistry, build_output_model
from .spec import AgentSpec


class EvalResult(BaseModel):
    index: int
    ok: bool
    detail: str = ""


class ValidatorVerdict(BaseModel):
    ok: bool
    built: bool
    audit: AuditReport
    evals: list[EvalResult] = []
    reason: str = ""


class Validador:
    """Build + evals. 'No hay agente sin evals.'

    1. El Auditor revisa el spec (determinista).
    2. Se compila el spec a un agente real (¿pasa create_model?).
    3. (opcional) Se corren los evals del spec contra el agente compilado.

    `ok` solo si las tres pasan. Si falla, el orquestador llama al fantasma.
    """

    def __init__(self, auditor: Auditor | None = None):
        self.auditor = auditor or Auditor()

    async def validate(
        self,
        spec: AgentSpec,
        taken_ids: list[str] | None = None,
        run_evals: bool = False,
    ) -> ValidatorVerdict:
        audit = self.auditor.audit(spec, taken_ids)

        built = True
        reason = ""
        agent: ConstructedAgent | None = None
        try:
            build_output_model(spec)         # ¿compila el schema?
            agent = ConstructedAgent(spec)   # ¿compila el agente?
        except Exception as exc:             # noqa: BLE001 — cualquier fallo de compilación
            built = False
            reason = f"no compila: {type(exc).__name__}: {exc}"

        eval_results: list[EvalResult] = []
        if run_evals and built and audit.ok and agent is not None:
            for i, ev in enumerate(spec.evals):
                ctx: dict[str, Any] = dict(ev.get("input") or {})
                try:
                    await agent.run(ctx)
                    eval_results.append(EvalResult(index=i, ok=True))
                except Exception as exc:  # noqa: BLE001
                    eval_results.append(EvalResult(index=i, ok=False, detail=str(exc)[:200]))

        evals_ok = all(r.ok for r in eval_results) if eval_results else True
        ok = audit.ok and built and evals_ok
        if ok:
            reason = "apto ✓"
        elif not audit.issues and built and not evals_ok:
            reason = "evals fallaron"
        elif audit.issues:
            reason = "auditoría: " + " · ".join(audit.issues)

        return ValidatorVerdict(ok=ok, built=built, audit=audit, evals=eval_results, reason=reason)
