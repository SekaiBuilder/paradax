import pytest

from agent_os.factory.skill import Skill
from agent_os.factory.skill_wire import SkillWireError, decode_skill, encode_skill


def _full_skill() -> dict:
    return Skill(
        id="web-selectors",
        name="Selectores reales",
        kind="capability",
        description="Extrae selectores reales.",
        tags=["web", "selectores"],
        tools=["http_get"],
        prompt="Usa solo selectores del inventario.",
        examples=[{"input": "x", "output": ["c", "#y"]}],
        evals=[{"input": "sin inventario", "expect": "rechaza"}],
        output_schema={"plan": "list"},
        created_by="constructor",
        version=3,
    ).model_dump()


def test_round_trip_lossless():
    skill = _full_skill()
    assert decode_skill(encode_skill(skill)) == skill


def test_minimal_skill_omits_defaults():
    skill = Skill(id="bare", name="Bare", kind="tool").model_dump()
    compact = encode_skill(skill)
    # solo los obligatorios deben quedar (id, name, kind)
    assert set(compact) == {"i", "n", "k"}
    assert compact["k"] == "t"  # kind codificado a una letra
    assert decode_skill(compact) == skill


def test_kind_is_short_coded():
    skill = Skill(id="p", name="P", kind="prompt").model_dump()
    assert encode_skill(skill)["k"] == "p"
    assert decode_skill({"i": "p", "n": "P", "k": "p"})["kind"] == "prompt"


def test_nested_content_preserved_verbatim():
    skill = _full_skill()
    compact = encode_skill(skill)
    # lo anidado no se toca: nada de short-keys dentro de examples/evals
    assert compact["x"] == [{"input": "x", "output": ["c", "#y"]}]


def test_missing_required_raises():
    with pytest.raises(SkillWireError):
        encode_skill({"name": "no id", "kind": "tool"})
    with pytest.raises(SkillWireError):
        decode_skill({"n": "no id", "k": "t"})


def test_unknown_field_raises():
    with pytest.raises(SkillWireError):
        encode_skill({"id": "x", "name": "X", "kind": "tool", "bogus": 1})
    with pytest.raises(SkillWireError):
        decode_skill({"i": "x", "n": "X", "k": "t", "zz": 1})


def test_skill_to_from_wire_helpers():
    skill = Skill(id="rt", name="RT", kind="eval", tags=["a"])
    assert Skill.from_wire(skill.to_wire()) == skill
