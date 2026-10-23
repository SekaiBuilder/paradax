from __future__ import annotations

"""Glyph: el protocolo compacto UNIVERSAL de salida de los agentes.

Generaliza el `wire` (que solo comprimía acciones de navegador) a cualquier
agente construido. La idea física, medible y honesta:

  La potencia de un LLM se gasta POR TOKEN generado. El nombre de cada campo
  del JSON de salida se repite en cada respuesta y cuesta tokens. Si el agente
  emite claves de 1-2 caracteres en vez de `posibles_errores`, genera menos
  tokens → responde más rápido, ocupa menos KV-cache, gasta menos energía. El
  MISMO Mac rinde más. No es magia: es densidad de información por token.

No es oscuridad: el mapa glyph→campo se deriva del schema del agente (público,
auditado) y `expand()` reconstruye el JSON completo antes de validar contra el
contrato. La seguridad es la validación, no el secreto.

Estrategia de despliegue (igual que wire):
  - El maestro genérico (7B/30B) habla JSON verboso — es lo fiable para él.
  - El ALUMNO especializado se entrena para emitir glyph nativo: ahí el ahorro
    es gratis y compuesto. Así el lenguaje propio "vive" en los pesos del
    modelo del agente, no en un prompt.
"""

from typing import Any

# Códigos estables y legibles: primera letra del campo + desambiguación.
# Determinista → el mismo schema produce siempre el mismo mapa (reproducible
# para entrenar al alumno).


def glyph_map(fields: list[str]) -> dict[str, str]:
    """field → glyph. Asigna la 1ª letra libre; si colisiona, añade índice."""
    used: set[str] = set()
    mapping: dict[str, str] = {}
    for f in fields:
        base = next((c for c in f.lower() if c.isalnum()), "x")
        code = base
        i = 1
        while code in used:
            code = f"{base}{i}"
            i += 1
        used.add(code)
        mapping[f] = code
    return mapping


def compress(payload: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    """JSON verboso → JSON glyph (para transcodificar datos del maestro)."""
    m = glyph_map(fields)
    return {m.get(k, k): v for k, v in payload.items()}


def expand(compact: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    """JSON glyph → JSON verboso (antes de validar contra el contrato).

    Tolerante: si el modelo emitió el nombre completo igualmente, se respeta.
    """
    inv = {g: f for f, g in glyph_map(fields).items()}
    out: dict[str, Any] = {}
    for k, v in compact.items():
        out[inv.get(k, k)] = v
    return out


def legend(fields: list[str]) -> str:
    """Línea para el prompt: enseña al modelo el mapa glyph→campo del turno."""
    m = glyph_map(fields)
    pairs = ", ".join(f'"{g}"={f}' for f, g in m.items())
    return pairs


def savings(fields: list[str], tokenizer: Any = None) -> dict[str, Any]:
    """Mide el ahorro de tokens SOLO por las claves (peor caso: 1 aparición
    por campo). En outputs con listas de dicts el ahorro se multiplica por el
    nº de elementos. Si no hay tokenizer, aproxima por caracteres/4."""
    verbose = "".join(f'"{f}":' for f in fields)
    compact = "".join(f'"{g}":' for g in glyph_map(fields).values())
    if tokenizer is not None:
        vt = len(tokenizer.encode(verbose))
        ct = len(tokenizer.encode(compact))
    else:
        vt, ct = len(verbose) // 4 + 1, len(compact) // 4 + 1
    return {
        "verbose_tokens": vt,
        "compact_tokens": ct,
        "ahorro_tokens": vt - ct,
        "ratio": round(vt / ct, 2) if ct else 0.0,
    }
