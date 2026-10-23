from __future__ import annotations

from typing import Any

from ..config import DEFAULT_MODEL, FAST_MODEL, PM_MODEL
from ..core.events import BUS
from .entrenador import Entrenador
from .factory import AgentFactory
from .project import Project, ProjectStore
from .skills_definer import SkillsDefinerAgent
from .team_planner import TeamPlannerAgent


class ProjectManager:
    """El agente que escucha un proyecto y lo lleva a 'ready'.

    Orquesta su sub-equipo de planificación y luego la fábrica:

        objetivo
          → Team Planner      (cuántos agentes + nombres)
          → Skills Definer    (habilidades por agente → encargo al Constructor)
          → Constructor       (fabrica cada agente) + Validador
          → Entrenador        (los agentes creados entran a la cola de destilación)
          → proyecto listo
    """

    def __init__(
        self,
        store: ProjectStore | None = None,
        factory: AgentFactory | None = None,
        planner: TeamPlannerAgent | None = None,
        definer: SkillsDefinerAgent | None = None,
        entrenador: Entrenador | None = None,
    ):
        self.store = store or ProjectStore()
        self.factory = factory or AgentFactory()
        self.planner = planner or TeamPlannerAgent()
        self.definer = definer or SkillsDefinerAgent()
        self.entrenador = entrenador or Entrenador()

    def _say(self, project: Project, frm: str, to: str, msg: str) -> None:
        """Registra un handoff como diálogo: A → B se dicen algo (no solo eventos)."""
        project.note(f"🗣 {frm} → {to}: {msg}")
        BUS.publish("dialogue", {"project": project.id, "from": frm, "to": to, "text": msg})
        self.store.save(project)

    async def build_team(self, project: Project, model: str = PM_MODEL) -> Project:
        BUS.publish("project_build_started", {"project": project.id, "goal": project.goal})
        project.status = "planning"
        project.agents = []
        project.note("PM: planificando el equipo")
        self.store.save(project)

        # ── Team Planner ─────────────────────────────────────────────────────
        try:
            BUS.publish("agent_started", {"agent": "team_planner", "reads": ["goal"]})
            team_plan = await self.planner.run({"goal": project.goal, "model": model})
        except Exception as exc:  # noqa: BLE001
            return self._fail(project, f"Team Planner falló: {exc}")
        project.team_plan = team_plan.model_dump()
        names = ", ".join(a.name for a in team_plan.agents)
        BUS.publish("agent_completed", {"agent": "team_planner", "summary": f"{len(team_plan.agents)} agentes"})
        self._say(project, "Planificador de equipo", "Definidor de habilidades",
                  f"equipo de {len(team_plan.agents)}: {names}. Define sus habilidades.")

        # ── Skills Definer ───────────────────────────────────────────────────
        try:
            BUS.publish("agent_started", {"agent": "skills_definer", "reads": ["team_plan"]})
            briefs = await self.definer.run({
                "goal": project.goal,
                "team_plan": project.team_plan,
                "skills_catalog": self.factory.skills_catalog(),
                "model": model,
            })
        except Exception as exc:  # noqa: BLE001
            return self._fail(project, f"Skills Definer falló: {exc}")
        project.briefs = [b.model_dump() for b in briefs.briefs]
        BUS.publish("agent_completed", {"agent": "skills_definer", "summary": f"{len(briefs.briefs)} encargos"})
        self._say(project, "Definidor de habilidades", "Constructor",
                  f"te paso {len(briefs.briefs)} encargos con sus skills. Fabrícalos.")

        # ── Constructor (uno por agente) + Validador ─────────────────────────
        project.status = "building"
        self.store.save(project)
        created: list[str] = []
        for brief in briefs.briefs:
            taken = self.factory.taken_ids() + created
            try:
                spec = await self.factory.constructor.run({
                    "request": _enrich(brief),
                    "skills_catalog": self.factory.skills_catalog(),
                    "taken_ids": taken,
                    "model": model,
                })
            except Exception as exc:  # noqa: BLE001
                project.note(f"✗ {brief.agent_name}: el Constructor no pudo ({str(exc)[:80]})")
                continue
            verdict = await self.factory.validador.validate(spec, taken)
            if not verdict.ok:
                project.note(f"✗ {brief.agent_name}: validación falló ({verdict.reason})")
                continue
            spec.project = project.id
            self.factory.registry.register(spec)
            created.append(spec.id)
            project.agents.append(spec.id)
            BUS.publish("agent_registered", {"agent": spec.id, "name": spec.name, "project": project.id})
            self._say(project, "Validador", "Entrenador",
                      f"'{spec.id}' ({brief.agent_name}) apto ✓ — cuando puedas, destílalo.")

        # ── Entrenador (cola de destilación) ─────────────────────────────────
        for aid in created:
            st = self.entrenador.status(aid)
            project.note(f"entrenador: '{aid}' corre con {st['engine']} (alumno propio cuando se destile)")

        project.status = "ready" if created else "failed"
        project.note("✅ proyecto listo" if created else "no se pudo crear ningún agente")
        BUS.publish("project_build_finished", {
            "project": project.id, "status": project.status, "agents": created,
        })
        return self.store.save(project)

    def _fail(self, project: Project, reason: str) -> Project:
        project.status = "failed"
        project.note(f"✗ {reason}")
        BUS.publish("project_build_finished", {"project": project.id, "status": "failed", "reason": reason})
        return self.store.save(project)

    def persona(self, project: Project) -> str:
        from .system_map import grounded_persona
        agents = ", ".join(project.agents) or "ninguno todavía"
        role = f"""Eres el Project Manager de Paradax para el proyecto «{project.name}».
Objetivo del proyecto: {project.goal}
Estado: {project.status}
Agentes del equipo: {agents}

Escuchas al usuario sobre ESTE proyecto y coordinas la fábrica. Para construir el
equipo trabajas con el Planificador de equipo y el Definidor de habilidades, y
luego el Constructor los fabrica y el Entrenador los especializa. Si el usuario
pide construir el equipo, dile que pulse «Construir equipo»."""
        return grounded_persona(role)


def _enrich(brief: Any) -> str:
    """Convierte un brief del Skills Definer en el encargo que recibe el Constructor."""
    parts = [brief.need]
    if brief.skills:
        parts.append(f"Skills sugeridas: {', '.join(brief.skills)}.")
    if brief.tools:
        parts.append(f"Tools sugeridas: {', '.join(brief.tools)}.")
    return " ".join(parts)
