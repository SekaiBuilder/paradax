from __future__ import annotations

"""Wire: el formato compacto en el que los agentes (y los modelos alumnos
fine-tuneados) se comunican.

Diseño:
- NO es un formato secreto: cada mensaje se valida contra el schema y todo
  queda auditado en SQLite. La seguridad es la validación, no la oscuridad.
- Ahorra tokens donde de verdad cuesta: en lo que el LLM genera. Una acción
  verbosa {"accion": "click", "selector": "#x"} (~12 tokens) se convierte en
  ["c", "#x"] (~6 tokens). En un plan de 14 acciones el ahorro es ~2.5x.
- El maestro (30B) sigue hablando JSON verboso — es fiable para él. El códec
  transcodifica al formato compacto para entrenar al alumno; el alumno lo
  emite nativo y `decode_plan` lo devuelve al formato que consume el recorder.

Acción compacta = lista posicional. Primer elemento: código de 1 letra.
    ["w", 1000]          esperar ms
    ["c", "#sel"]        click
    ["e", "#sel", "txt"] escribir (fill)
    ["t", "#sel", "txt"] tipear (type)
    ["s", 400]           scroll y
    ["h", "#sel"]        hover
    ["k", "Enter"]       tecla
    ["x", 270, 450]      clickxy
    ["g", "https://…"]   ir
    ["m"]                marcar
    ["?", {...}]         escape: acción con campos no estándar, dict original
"""

from typing import Any

# (código, campos posicionales tras el código) por tipo de acción.
_SPEC: dict[str, tuple[str, tuple[str, ...]]] = {
    "esperar": ("w", ("ms",)),
    "click": ("c", ("selector",)),
    "escribir": ("e", ("selector", "texto")),
    "tipear": ("t", ("selector", "texto")),
    "scroll": ("s", ("y",)),
    "hover": ("h", ("selector",)),
    "tecla": ("k", ("tecla",)),
    "clickxy": ("x", ("x", "y")),
    "ir": ("g", ("url",)),
    "marcar": ("m", ()),
}
_BY_CODE = {code: (kind, fields) for kind, (code, fields) in _SPEC.items()}


class WireError(ValueError):
    pass


def encode_action(action: dict[str, Any]) -> list[Any]:
    kind = action.get("accion")
    spec = _SPEC.get(kind)
    if spec is None:
        raise WireError(f"acción desconocida: {kind!r}")
    code, fields = spec
    extras = set(action) - {"accion", *fields}
    if extras:
        # Campos fuera del estándar (p. ej. delay en tipear): escape verboso
        # antes que perder información en silencio.
        return ["?", dict(action)]
    return [code, *(action[f] for f in fields if f in action)]


def decode_action(item: list[Any]) -> dict[str, Any]:
    if not isinstance(item, list) or not item:
        raise WireError(f"acción compacta inválida: {item!r}")
    code = item[0]
    if code == "?":
        if len(item) != 2 or not isinstance(item[1], dict):
            raise WireError(f"escape '?' malformado: {item!r}")
        return dict(item[1])
    spec = _BY_CODE.get(code)
    if spec is None:
        raise WireError(f"código desconocido: {code!r}")
    kind, fields = spec
    values = item[1:]
    if len(values) > len(fields):
        raise WireError(f"sobran valores para {kind}: {item!r}")
    return {"accion": kind, **dict(zip(fields, values))}


def encode_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Plan verboso → compacto. Claves: f=actions_file, g=gif, a=acciones."""
    return {
        "f": plan["actions_file_name"],
        "g": plan["gif_output_name"],
        "a": [encode_action(a) for a in plan["actions"]],
    }


def decode_plan(compact: dict[str, Any]) -> dict[str, Any]:
    """Compacto → formato que consumen recorder y pipeline."""
    for key in ("f", "g", "a"):
        if key not in compact:
            raise WireError(f"plan compacto sin clave '{key}'")
    if not isinstance(compact["a"], list) or not compact["a"]:
        raise WireError("plan compacto sin acciones")
    return {
        "actions_file_name": compact["f"],
        "gif_output_name": compact["g"],
        "actions": [decode_action(a) for a in compact["a"]],
    }
