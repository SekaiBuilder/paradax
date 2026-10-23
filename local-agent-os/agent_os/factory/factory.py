from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ..config import DEFAULT_MODEL
from ..core.events import BUS
from .auditor import Auditor
from .constructor import ConstructorAgent
from .entrenador import Entrenador
from .ghost import Ghost, StagedProposal
from .loader import DYNAMIC, DynamicRegistry
from .spec import AgentSpec
from .validator import Validador, ValidatorVerdict
from .skill_master import SkillMaster


class BuildReport(BaseModel):
    request: str
    ok: bool
    registered: bool = False
    spec: dict[str, Any] | None = None
    verdict: dict[str, Any] | None = None
    proposal: dict[str, Any] | None = None   # propuesta del fantasma (staging)
    error: str = ""


class AgentFactory:
    """El orquestador de la fábrica: Constructor → Auditor → Validador →
    (pasa) registrar · (falla) fantasma. No hace el trabajo; reparte y verifica,
    como el orquestador de media."""

    def __init__(
        self,
        skill_master: SkillMaster | None = None,
        registry: DynamicRegistry | None = None,
        ghost: Ghost | None = None,
        constructor: ConstructorAgent | None = None,
        validador: Validador | None = None,
        entrenador: Entrenador | None = None,
    ):
        self.skills = skill_master or SkillMaster()
        self.registry = registry or DYNAMIC
        self.ghost = ghost or Ghost()
        self.constructor = constructor or ConstructorAgent()
        self.validador = validador or Validador(Auditor())
        self.entrenador = entrenador or Entrenador()

    def taken_ids(self) -> list[str]:
        ids = ["orchestrator", *self.registry.ids()]
        try:
            from ..agents import REGISTRY
            ids += list(REGISTRY.keys())
        except Exception:
            pass
        return ids

    def skills_catalog(self) -> list[dict[str, Any]]:
        return [
            {"id": s.id, "name": s.name, "description": s.description, "tags": s.tags}
            for s in self.skills.all()
        ]

    async def build(
        self, request: str, model: str = DEFAULT_MODEL, escalate: bool = False, run_evals: bool = False
    ) -> BuildReport:
        BUS.publish("factory_started", {"request": request})
        taken = self.taken_ids()

        # ── Constructor ──────────────────────────────────────────────────────
        BUS.publish("agent_started", {"agent": "constructor", "reads": ["request", "skills_catalog"]})
        try:
            spec: AgentSpec = await self.constructor.run({  # type: ignore[assignment]
                "request": request,
                "skills_catalog": self.skills_catalog(),
                "taken_ids": taken,
                "model": model,
            })
        except Exception as exc:  # noqa: BLE001 — Constructor no pudo: candidato a fantasma
            BUS.publish("agent_failed", {"agent": "constructor", "error": str(exc)[:300]})
            return await self._maybe_escalate(request, f"constructor: {exc}", escalate)
        BUS.publish("agent_completed", {"agent": "constructor", "summary": f"spec '{spec.id}'"})

        # ── Validador (incluye Auditor) ──────────────────────────────────────
        BUS.publish("agent_started", {"agent": "validador", "reads": ["spec"]})
        verdict: ValidatorVerdict = await self.validador.validate(spec, taken, run_evals=run_evals)
        BUS.publish("agent_completed", {"agent": "validador", "summary": verdict.reason})

        if not verdict.ok:
            report = await self._maybe_escalate(request, verdict.reason, escalate)
            report.spec = spec.model_dump()
            report.verdict = verdict.model_dump()
            return report

        # ── Registrar ────────────────────────────────────────────────────────
        self.registry.register(spec)
        BUS.publish("agent_registered", {"agent": spec.id, "name": spec.name})
        BUS.publish("factory_finished", {"request": request, "status": "registered", "agent": spec.id})
        return BuildReport(
            request=request, ok=True, registered=True,
            spec=spec.model_dump(), verdict=verdict.model_dump(),
        )

    async def _maybe_escalate(self, request: str, reason: str, escalate: bool) -> BuildReport:
        if not escalate:
            BUS.publish("factory_finished", {"request": request, "status": "failed", "reason": reason})
            return BuildReport(request=request, ok=False, error=reason)
        BUS.publish("agent_started", {"agent": "ghost", "reads": ["failure"]})
        proposal: StagedProposal = await self.ghost.escalate(request, reason)
        BUS.publish("agent_completed", {"agent": "ghost", "summary": f"propuesta en staging: {proposal.id}"})
        BUS.publish("factory_finished", {"request": request, "status": "staged", "proposal": proposal.id})
        return BuildReport(request=request, ok=False, error=reason, proposal=proposal.model_dump())
