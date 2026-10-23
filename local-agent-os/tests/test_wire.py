from __future__ import annotations

import json

import pytest

from agent_os.core.wire import WireError, decode_action, decode_plan, encode_action, encode_plan

VERBOSE_PLAN = {
    "actions_file_name": "acciones-kanji.json",
    "gif_output_name": "kanji.gif",
    "actions": [
        {"accion": "esperar", "ms": 1000},
        {"accion": "click", "selector": ".ck-accept-btn"},
        {"accion": "esperar", "ms": 2500},
        {"accion": "click", "selector": "#tut-x"},
        {"accion": "esperar", "ms": 500},
        {"accion": "marcar"},
        {"accion": "click", "selector": "#btn-kanji"},
        {"accion": "escribir", "selector": "#respuesta", "texto": "火"},
        {"accion": "tecla", "tecla": "Enter"},
        {"accion": "clickxy", "x": 270, "y": 450},
        {"accion": "scroll", "y": 400},
        {"accion": "esperar", "ms": 1500},
    ],
}


def test_roundtrip_is_lossless():
    compact = encode_plan(VERBOSE_PLAN)
    restored = decode_plan(compact)
    assert restored == VERBOSE_PLAN


def test_compact_is_actually_smaller():
    verbose_len = len(json.dumps(VERBOSE_PLAN, ensure_ascii=False))
    compact_len = len(json.dumps(encode_plan(VERBOSE_PLAN), ensure_ascii=False))
    assert compact_len < verbose_len * 0.55, f"{compact_len} vs {verbose_len}"


def test_nonstandard_fields_use_escape_not_silent_loss():
    action = {"accion": "tipear", "selector": "#x", "texto": "hola", "delay": 120}
    encoded = encode_action(action)
    assert encoded[0] == "?"
    assert decode_action(encoded) == action


def test_unknown_action_rejected():
    with pytest.raises(WireError, match="desconocida"):
        encode_action({"accion": "explotar", "selector": "#x"})


def test_unknown_code_rejected():
    with pytest.raises(WireError, match="desconocido"):
        decode_action(["z", "#x"])


def test_too_many_values_rejected():
    with pytest.raises(WireError, match="sobran"):
        decode_action(["c", "#x", "extra"])


def test_malformed_plan_rejected():
    with pytest.raises(WireError, match="clave 'a'"):
        decode_plan({"f": "x.json", "g": "x.gif"})
    with pytest.raises(WireError, match="sin acciones"):
        decode_plan({"f": "x.json", "g": "x.gif", "a": []})
