from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .config import (
    NINEROUTER_API_KEY,
    NINEROUTER_BASE_URL,
    NINEROUTER_PREFIX,
    OLLAMA_BASE_URL,
    OLLAMA_NUM_CTX,
    OPEN_LICENSE_FAMILIES,
)

# La primera llamada a un modelo grande (30B ≈ 18 GB) puede tardar varios
# minutos solo en cargar a memoria. Un timeout corto hace que el plan caiga
# siempre al fallback sin que se note. Read-timeout largo, connect corto.
CHAT_TIMEOUT = httpx.Timeout(
    connect=5.0,
    read=float(os.getenv("OLLAMA_READ_TIMEOUT", "600")),
    write=30.0,
    pool=5.0,
)


async def list_models() -> list[str]:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
        resp.raise_for_status()
    data = resp.json()
    return [m["name"] for m in data.get("models", [])]


async def ensure_only_model(model: str) -> None:
    """Descarga de memoria cualquier OTRO modelo cargado en ollama.

    Motivo: un modelo residual (p.ej. el 30B con keep_alive de 30 min) puede
    ocupar casi toda la RAM y dejar al modelo pedido ESPERANDO en la cola de
    carga de ollama sin error visible — el agente muere por ReadTimeout sin
    haber generado un solo token. Llamar esto al inicio de cada run garantiza
    que el modelo del run tiene la memoria libre.

    Nunca lanza: cualquier fallo aquí no debe impedir el run (como mucho, el
    run sufrirá la cola — el statu quo anterior).
    """
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"{OLLAMA_BASE_URL}/api/ps")
            resp.raise_for_status()
            loaded = [m["name"] for m in resp.json().get("models", [])]
            for name in loaded:
                if name != model:
                    # keep_alive=0 con prompt vacío = idiom oficial de descarga.
                    await client.post(
                        f"{OLLAMA_BASE_URL}/api/generate",
                        json={"model": name, "keep_alive": 0},
                    )
    except Exception:
        pass


def _trace_call(kind: str, model: str) -> None:
    """Log de auditoría: qué modelo se pide y desde dónde. Activo solo si
    existe la variable de entorno PARADAX_TRACE_LLM (depuración)."""
    if not os.getenv("PARADAX_TRACE_LLM"):
        return
    try:
        import time as _t
        import traceback
        stack = [l.strip() for l in traceback.format_stack()[-6:-2]]
        with open("/tmp/paradax_llm_calls.log", "a", encoding="utf-8") as f:
            f.write(f"{_t.strftime('%H:%M:%S')} {kind} model={model}\n")
            for l in stack:
                f.write(f"    {l.splitlines()[0]}\n")
    except Exception:
        pass


def is_router_model(model: str) -> bool:
    return model.startswith(NINEROUTER_PREFIX)


def router_model_name(model: str) -> str:
    """Quita el prefijo "9r/" y exige licencia abierta. El nombre que queda es
    el de 9router (puede llevar su propio prefijo de proveedor, p. ej.
    "glm/glm-4.6"): se comprueba la familia en el último segmento."""
    name = model[len(NINEROUTER_PREFIX):]
    family = name.rsplit("/", 1)[-1].lower()
    if not family.startswith(OPEN_LICENSE_FAMILIES):
        raise ValueError(
            f"Modelo de 9router no permitido como maestro: {name!r} "
            f"(solo familias abiertas: {', '.join(OPEN_LICENSE_FAMILIES)})"
        )
    return name


def _router_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {NINEROUTER_API_KEY}"} if NINEROUTER_API_KEY else {}


async def _router_chat(model: str, messages: list[dict], temperature: float, json_mode: bool) -> str:
    payload: dict[str, Any] = {
        "model": router_model_name(model),
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=CHAT_TIMEOUT) as client:
        resp = await client.post(
            f"{NINEROUTER_BASE_URL}/chat/completions", json=payload, headers=_router_headers()
        )
        resp.raise_for_status()
    return resp.json()["choices"][0]["message"].get("content") or ""


def _extract_json(content: str) -> str:
    """Los modelos vía API a veces envuelven el JSON en ```json …``` o
    anteponen texto: nos quedamos con el primer objeto {…}."""
    start, end = content.find("{"), content.rfind("}")
    return content[start:end + 1] if start != -1 and end > start else content


async def stream_chat(model: str, system: str, messages: list[dict]) -> AsyncIterator[str]:
    _trace_call("stream_chat", model)
    if is_router_model(model):
        yield await _router_chat(
            model, [{"role": "system", "content": system}] + messages, 0.7, json_mode=False
        )
        return
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + messages,
        "stream": True,
        "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
        "options": {"temperature": 0.7, "num_ctx": OLLAMA_NUM_CTX},
    }
    async with httpx.AsyncClient(timeout=CHAT_TIMEOUT) as client:
        async with client.stream("POST", f"{OLLAMA_BASE_URL}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                chunk = data.get("message", {}).get("content", "")
                if chunk:
                    yield chunk
                if data.get("done"):
                    return


_NO_FORMAT: set[str] = set()


def _format_unavailable(resp: httpx.Response) -> bool:
    return resp.status_code >= 400 and "structured output is unavailable" in resp.text


async def chat_json(model: str, system: str, user: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
    """`schema` (JSON schema) restringe la decodificación en Ollama: el modelo
    no puede emitir tokens que lo rompan. Sin él, solo JSON válido de cualquier forma."""
    _trace_call("chat_json", model)
    if is_router_model(model):
        content = _extract_json(await _router_chat(
            model,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            0.1,
            json_mode=True,
        ))
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Model did not return valid JSON: {content[:500]}") from exc
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "format": schema or "json",
        # Mantener el modelo cargado entre runs: evita pagar la carga
        # completa (minutos) en cada plan.
        "keep_alive": os.getenv("OLLAMA_KEEP_ALIVE", "30m"),
        "options": {"temperature": 0.1, "num_ctx": OLLAMA_NUM_CTX},
    }
    if model in _NO_FORMAT:
        payload.pop("format")
    async with httpx.AsyncClient(timeout=CHAT_TIMEOUT) as client:
        resp = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
        if "format" in payload and _format_unavailable(resp):
            # Los modelos importados por MLX (Ollama ≥ 0.40) no tienen salida
            # estructurada: se pide sin `format` y se extrae el objeto JSON.
            _NO_FORMAT.add(model)
            payload.pop("format")
            resp = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
        resp.raise_for_status()
    content = resp.json().get("message", {}).get("content", "{}")
    if model in _NO_FORMAT:
        content = _extract_json(content)
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Model did not return valid JSON: {content[:500]}") from exc
