from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .. import db
from .agent import Agent, AgentError
from .events import BUS


class Pipeline:
    """Ejecuta agentes sobre un contexto compartido, registrando cada paso.

    El pipeline NO decide el flujo — eso es del orquestador. Solo:
    - filtra el contexto a las claves que el agente declara (`reads`)
    - valida la salida contra el schema del contrato
    - guarda la salida bajo `writes`
    - registra eventos agent_started / agent_completed / agent_failed
    """

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.ctx: dict[str, Any] = {}
        self.trace: list[dict[str, Any]] = []

    async def step(self, agent: Agent, **extra: Any) -> BaseModel:
        c = agent.contract
        # Sandbox: marca qué agente está en curso para que las tool calls que
        # haga durante agent.run() lleguen al Sentinel-Watch con su agent_id
        # correcto (habilita la verificación por contrato). Sin sandbox activo
        # es un no-op inofensivo (ToolRuntime.call lo ignora si no hay bus).
        from ..factory.tool_runtime import SANDBOX_AGENT_ID_VAR
        SANDBOX_AGENT_ID_VAR.set(c.id)
        self.ctx.update(extra)
        # Observabilidad: registrar el modelo EFECTIVO que usará este agente
        # (mismo cálculo que hace el agente) — clave para depurar qué modelo
        # corre de verdad cuando el run se lanzó con uno concreto.
        from .models import resolve_model
        eff_model, is_student = resolve_model(c.id, self.ctx.get("model", "(default)"))
        db.add_event(self.run_id, "agent_started",
                     {"agent": c.id, "reads": list(c.reads), "model": eff_model, "student": is_student})
        BUS.publish("agent_started", {"run_id": self.run_id, "agent": c.id, "reads": list(c.reads),
                                      "model": eff_model})
        try:
            result = await agent.run(self.ctx)
        except AgentError as exc:
            db.add_event(self.run_id, "agent_failed", {"agent": c.id, "error": str(exc)[:1000]})
            BUS.publish("agent_failed", {"run_id": self.run_id, "agent": c.id, "error": str(exc)[:300]})
            raise
        except Exception as exc:
            db.add_event(
                self.run_id,
                "agent_failed",
                {"agent": c.id, "error": f"{type(exc).__name__}: {exc}"[:1000]},
            )
            BUS.publish("agent_failed", {"run_id": self.run_id, "agent": c.id, "error": f"{type(exc).__name__}: {exc}"[:300]})
            raise AgentError(c.id, f"{type(exc).__name__}: {exc}") from exc

        payload = result.model_dump()
        self.ctx[c.writes] = payload
        self.trace.append({"agent": c.id, "writes": c.writes})
        # Se registra también el INPUT del agente (sus reads resueltos): un run
        # verificado se convierte así en ejemplo de entrenamiento del alumno
        # especialista — sin input no hay dataset. Truncado para no inflar la DB.
        agent_input = {k: _clip(self.ctx.get(k)) for k in c.reads if k != "model"}
        # source: "model" (1er intento), "model_retry_N" o "fallback:…" — la
        # señal de dureza de la tarea que el Proposer usa para buscar debilidades.
        source = getattr(agent, "_last_source", "model")
        db.add_event(self.run_id, "agent_completed",
                     {"agent": c.id, "output": payload, "input": agent_input,
                      "model": eff_model, "source": source})
        # Al bus solo un resumen ligero (no el payload entero: acota el frame SSE).
        BUS.publish("agent_completed", {
            "run_id": self.run_id, "agent": c.id, "writes": c.writes,
            "summary": _summarize(c.writes, payload),
        })
        return result


def _clip(value: Any, max_chars: int = 4000) -> Any:
    """Trunca valores largos del input registrado (la DB no es un data lake)."""
    if isinstance(value, str) and len(value) > max_chars:
        return value[:max_chars] + f"…[+{len(value) - max_chars} chars]"
    return value


def _summarize(writes: str, payload: dict[str, Any]) -> str:
    """Frase corta y legible de lo que produjo el agente — para el feed en vivo."""
    if writes == "inventory":
        n = len(payload.get("ids", [])) + len(payload.get("classes", []))
        return f"inventario: {n} selectores reales" if payload.get("fetched") else "página no accesible"
    if writes == "plan":
        return f"plan {payload.get('plan_source', '?')}: {len(payload.get('actions', []))} acciones"
    if writes == "gif":
        v = payload.get("verification", {})
        return f"GIF {round(float(v.get('duration') or 0), 1)}s, {payload.get('failed_steps', 0)} fallos"
    if writes == "verdict":
        return "apto ✓" if payload.get("ok") else f"reparar: {payload.get('reason', '')[:60]}"
    if writes == "voice":
        return f"guion {payload.get('language', '')}: {payload.get('text', '')[:50]}…"
    if writes == "reel":
        v = payload.get("verification", {})
        return f"reel {round(float(v.get('duration') or 0), 1)}s"
    return writes
