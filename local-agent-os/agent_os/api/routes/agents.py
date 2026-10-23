from __future__ import annotations

"""Chat directo con agentes (sistema, pipeline de media y construidos)."""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ... import ollama
from ...agents import REGISTRY
from ...config import DEFAULT_MODEL
from ...core.events import BUS
from ...core.models import resolve_model
from ...factory import system_agents as sysagents
from ...factory.loader import DYNAMIC
from ..state import (
    ChatRequest, chat_histories, in_language, _agent_project,
    _agent_tier, _project_visible,
)

router = APIRouter()


def _persona_for(agent_id: str) -> str:
    if agent_id == "orchestrator":
        flow = " → ".join(a.contract.name for a in REGISTRY.values())
        return f"""Eres el Orchestrator de Paradax, el agente coordinador.

Tu rol: SOLO repartes y verificas — nunca haces el trabajo tú mismo.

Pipeline que coordinas: {flow}.

Cada agente tiene contrato: claves de contexto que lee, schema de salida
obligatorio y herramientas permitidas. Si un agente falla su contrato, el run
falla con el motivo registrado — no hay fallbacks silenciosos.

Eres conciso, técnico y directo. Usa español salvo que el usuario hable otro idioma."""

    agent = REGISTRY.get(agent_id)
    if not agent:
        return f"Eres el agente {agent_id} de Paradax. Responde en español salvo que el usuario hable otro idioma."

    c = agent.contract
    if c.uses_llm:
        model, is_student = resolve_model(c.id, DEFAULT_MODEL)
        if is_student:
            engine = (
                f"Corres sobre tu PROPIO modelo especializado '{model}', "
                "fine-tuneado por destilación con tus runs verificados. Hablas el "
                "protocolo compacto wire y producción lo decodifica."
            )
        else:
            engine = f"Usas el modelo maestro '{model}' (aún no tienes especialista propio promocionado)."
    else:
        engine = "Eres determinista: no usas LLM."

    base = f"""Eres {c.name} ({c.id}) de Paradax.

Tu especialidad: {c.description}.
Contexto que lees: {', '.join(c.reads)}.
Tu salida obligatoria: schema {c.output_model.__name__} (clave '{c.writes}' del pipeline).
Herramientas permitidas: {', '.join(c.allowed_tools) or 'ninguna (solo razonamiento)'}.
{engine}

Cuando el usuario te pregunte, explica tu rol dentro del pipeline y cómo harías
su pedido respetando tu contrato. Usa español salvo que el usuario hable otro idioma."""

    if c.uses_llm and hasattr(agent, "system_prompt"):
        base += f"\n\nTu prompt operativo real:\n---\n{agent.system_prompt[:2000]}\n---"
    return base


@router.get("/api/agents")
def agents_list(project: str | None = None):
    def with_model(agent):
        summary = agent.contract.summary()
        if agent.contract.uses_llm:
            model, is_student = resolve_model(agent.contract.id, DEFAULT_MODEL)
            summary["active_model"] = model
            summary["specialized"] = is_student
        return summary

    def constructed(agent):
        summary = with_model(agent)
        summary["constructed"] = True  # fabricado por el Constructor
        summary["project"] = _agent_project(agent)
        summary["tier"] = _agent_tier(agent)
        return summary

    return {
        "agents": [
            {"id": "orchestrator", "name": "Orchestrator", "description": "Solo reparte y verifica"},
            *[with_model(agent) for agent in REGISTRY.values()],
            *[constructed(agent) for agent in DYNAMIC.all()
              if _project_visible(_agent_project(agent), project)],
        ]
    }


# ── Agent chat ────────────────────────────────────────────────────────────────

@router.post("/api/agents/{agent_id}/chat")
async def agent_chat(agent_id: str, req: ChatRequest):
    # Persona fresca por request: refleja un alumno promocionado en caliente
    # sin reiniciar el servidor.
    if sysagents.is_system_agent(agent_id):
        if not sysagents.is_contactable(agent_id):
            raise HTTPException(status_code=403, detail="este agente no es contactable (interno o durmiente)")
        persona = sysagents.persona(agent_id)
    elif agent_id == "orchestrator" or agent_id in REGISTRY:
        persona = _persona_for(agent_id)
    else:
        persona = f"Eres el agente {agent_id} de Paradax. Responde en español salvo que el usuario hable otro idioma."
    persona = in_language(persona, req.lang)
    history = chat_histories.setdefault(agent_id, [])
    history.append({"role": "user", "content": req.message})

    BUS.publish("chat_message", {"agent": agent_id, "role": "user", "text": req.message[:200]})

    async def generate():
        full = ""
        try:
            # Agentes con tools (p.ej. el Gestor de automatizaciones) ejecutan
            # acciones reales ANTES de redactar; luego confirman lo que hicieron.
            system = persona
            from ...factory.agent_tools import has_tools, run_tool_loop
            if has_tools(agent_id):
                actions = await run_tool_loop(agent_id, req.model, persona, history)
                if actions:
                    system = (
                        persona
                        + "\n\n--- Acciones que ACABAS de ejecutar ---\n"
                        + "\n".join(actions)
                        + "\n\nConfirma al usuario en lenguaje natural, breve y claro, lo que "
                        "hiciste. Si creaste una programación, menciona la hora estimada de "
                        "arranque y por qué. Si algo falló (ok=false o ERROR), díselo con "
                        "honestidad y sugiere cómo corregirlo. No muestres JSON."
                    )
                    BUS.publish("chat_message", {"agent": agent_id, "role": "tool",
                                                 "text": " | ".join(actions)[:200]})
            async for chunk in ollama.stream_chat(req.model, system, history):
                full += chunk
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
            history.append({"role": "assistant", "content": full})
            BUS.publish("chat_message", {"agent": agent_id, "role": "assistant", "text": full[:200]})
            yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            if history and history[-1]["role"] == "user":
                history.pop()
            yield f"data: {json.dumps({'error': str(exc)[:500]}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/agents/{agent_id}/chat/history")
def get_chat_history(agent_id: str):
    return {"history": chat_histories.get(agent_id, [])}


@router.delete("/api/agents/{agent_id}/chat/history")
def clear_chat_history(agent_id: str):
    chat_histories.pop(agent_id, None)
    return {"ok": True}
