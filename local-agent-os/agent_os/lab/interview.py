from __future__ import annotations

"""Entrevista aislada con un modelo en cuarentena.

Barreras (todas en el servidor; la UI no puede saltárselas):
  1. Solo modelos en cuarentena: el nombre se valida contra la lista de
     vetados y de casos. No sirve para hablar con un modelo cualquiera.
  2. Solo texto: se llama a /api/chat de Ollama local sin 'tools' ni
     'format'. No existe ningún camino para que su salida se ejecute.
  3. Destino fijo: OLLAMA_BASE_URL de la config, nunca uno que mande el cliente.
  4. Límites: mensaje ≤ 2000 caracteres, respuesta ≤ 4000, 1024 tokens,
     una sesión activa por modelo a la vez.
  5. Salida saneada de códigos de control; la UI la pinta como texto, no HTML.
  6. Todo queda en la memoria del modelo (registro de solo-añadir).
"""

import asyncio
import json
import re
from collections.abc import AsyncIterator

import httpx

from ..config import OLLAMA_BASE_URL
from ..training import quarantine
from ..training.quarantine import MAX_REPLY, sanitize
from . import memory

MAX_MESSAGE = 2000
_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{6,40}$")
_locks: dict[str, asyncio.Lock] = {}


class InterviewError(ValueError):
    pass


def check(model: str, session_id: str, message: str) -> str:
    if model not in memory.quarantined_models():
        raise InterviewError("ese modelo no está en cuarentena: el Laboratorio solo habla con modelos vetados")
    if model in quarantine.deleted():
        raise InterviewError("ese modelo fue eliminado de Ollama: quedan sus casos y su memoria, pero ya no puede responder")
    if not _SESSION_RE.match(session_id or ""):
        raise InterviewError("id de sesión inválido")
    message = sanitize(message or "").strip()
    if not message:
        raise InterviewError("mensaje vacío")
    if len(message) > MAX_MESSAGE:
        raise InterviewError(f"mensaje demasiado largo (máx. {MAX_MESSAGE} caracteres)")
    return message


async def reply(model: str, session_id: str, message: str) -> AsyncIterator[str]:
    """Valida, construye la memoria, transmite la respuesta y la registra."""
    message = check(model, session_id, message)
    lock = _locks.setdefault(model, asyncio.Lock())
    if lock.locked():
        raise InterviewError("ya hay una respuesta en curso con este modelo; espera a que termine")
    async with lock:
        history = memory.session_turns(model, session_id)[-memory.SESSION_TURNS:]
        messages = [{"role": "system", "content": memory.build_system(model, session_id)}]
        messages += [{"role": t["role"], "content": t["text"]} for t in history]
        messages.append({"role": "user", "content": message})
        memory.append_turn(model, session_id, "user", message)

        full = ""
        try:
            async with httpx.AsyncClient(timeout=300) as client:
                async with client.stream("POST", f"{OLLAMA_BASE_URL}/api/chat", json={
                    "model": model, "messages": messages, "stream": True,
                    "options": {"temperature": 0.3, "num_predict": 1024, "num_ctx": 8192},
                }) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        chunk = sanitize(data.get("message", {}).get("content", ""))
                        if chunk and len(full) < MAX_REPLY:
                            chunk = chunk[: MAX_REPLY - len(full)]
                            full += chunk
                            yield chunk
                        if data.get("done"):
                            break
        finally:
            memory.append_turn(model, session_id, "assistant", full or "(sin respuesta)")
