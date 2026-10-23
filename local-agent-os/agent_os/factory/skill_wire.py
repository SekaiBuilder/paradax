from __future__ import annotations

"""Skill-wire: el formato compacto en el que el Skill Master guarda las skills.

Extiende la filosofía del wire de acciones (`core/wire.py`) a las skills:

- NO es un lenguaje de programación. Es un formato de DATOS compacto. La
  decisión de "specs-como-datos SÍ, lenguaje ejecutable propio NO" sigue en pie.
- Ahorra donde duele: nombres de campo de una letra y omisión de todo lo que
  está en su valor por defecto. Una skill verbosa de ~400 bytes baja a ~120.
- Round-trip lossless: `decode_skill(encode_skill(x)) == x` para toda skill
  válida. Lo anidado (examples/evals/output_schema) se preserva tal cual — así
  el contenido arbitrario nunca se corrompe.

Verboso → compacto (solo se escribe lo que no es default):
    id → i   name → n   kind → k   description → d   tags → t   tools → o
    prompt → p   examples → x   evals → e   output_schema → s
    created_by → b   version → v
"""

from typing import Any

_FIELD_TO_SHORT: dict[str, str] = {
    "id": "i", "name": "n", "kind": "k", "description": "d", "tags": "t",
    "tools": "o", "prompt": "p", "examples": "x", "evals": "e",
    "output_schema": "s", "created_by": "b", "version": "v",
}
_SHORT_TO_FIELD = {short: field for field, short in _FIELD_TO_SHORT.items()}

_KIND_TO_SHORT = {"tool": "t", "prompt": "p", "example": "x", "eval": "e", "schema": "s", "capability": "c"}
_SHORT_TO_KIND = {short: kind for kind, short in _KIND_TO_SHORT.items()}

# Valor por defecto de cada campo: si la skill lo tiene, no se serializa.
_DEFAULTS: dict[str, Any] = {
    "description": "", "tags": [], "tools": [], "prompt": "",
    "examples": [], "evals": [], "output_schema": {},
    "created_by": "human", "version": 1,
}
_REQUIRED = ("id", "name", "kind")


class SkillWireError(ValueError):
    pass


def encode_skill(skill: dict[str, Any]) -> dict[str, Any]:
    """Skill verbosa → compacta. Omite campos en su valor por defecto."""
    for key in _REQUIRED:
        if not skill.get(key):
            raise SkillWireError(f"skill sin campo obligatorio '{key}'")
    out: dict[str, Any] = {}
    for field, value in skill.items():
        short = _FIELD_TO_SHORT.get(field)
        if short is None:
            raise SkillWireError(f"campo de skill desconocido: {field!r}")
        if field not in _REQUIRED and value == _DEFAULTS.get(field):
            continue  # default → se omite
        if field == "kind":
            value = _KIND_TO_SHORT.get(value, value)
        out[short] = value
    return out


def decode_skill(compact: dict[str, Any]) -> dict[str, Any]:
    """Compacta → verbosa, restaurando defaults de los campos omitidos."""
    out: dict[str, Any] = dict(_DEFAULTS)
    for short, value in compact.items():
        field = _SHORT_TO_FIELD.get(short)
        if field is None:
            raise SkillWireError(f"código de skill desconocido: {short!r}")
        if field == "kind":
            value = _SHORT_TO_KIND.get(value, value)
        out[field] = value
    for key in _REQUIRED:
        if not out.get(key):
            raise SkillWireError(f"skill compacta sin '{_FIELD_TO_SHORT[key]}' ({key})")
    return out


def encode_many(skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [encode_skill(s) for s in skills]


def decode_many(compact: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [decode_skill(c) for c in compact]


if __name__ == "__main__":
    import json

    skill = {
        "id": "web-selectors",
        "name": "Inspección de selectores reales",
        "kind": "capability",
        "description": "Extrae ids/clases/data-attrs reales de una página y planifica solo con ellos.",
        "tags": ["web", "selectores", "playwright"],
        "tools": ["http_get", "record_page_gif"],
        "prompt": "Usa SOLO selectores presentes en el inventario real. Si no existe, no lo inventes.",
        "examples": [{"input": "gif del kanji 水", "output": ["c", "#btn-kanji"]}],
        "evals": [{"input": "página sin inventario", "expect": "rechaza el plan"}],
        "output_schema": {},
        "created_by": "human",
        "version": 1,
    }
    compact = encode_skill(skill)
    assert decode_skill(compact) == skill, "round-trip debe ser lossless"

    verbose_len = len(json.dumps(skill, ensure_ascii=False))
    compact_len = len(json.dumps(compact, ensure_ascii=False))
    print("compacto:", json.dumps(compact, ensure_ascii=False))
    print(f"\nverboso: {verbose_len} bytes  ·  compacto: {compact_len} bytes  ·  {verbose_len / compact_len:.2f}× menos")
