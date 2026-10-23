from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..core.agent import LLMAgent
from ..core.contract import AgentContract
from ..core.models import resolve_model
from ..core.schemas import ActionPlan
from ..core.wire import WireError, decode_action

PROMPT_PATH = Path(__file__).parent / "prompts" / "action_planner.md"
STUDENT_PROMPT_PATH = Path(__file__).parent / "prompts" / "student_planner.md"

ALLOWED_ACTIONS = {
    "esperar", "click", "escribir", "tipear", "scroll", "hover", "tecla", "clickxy", "ir", "marcar"
}

# Prefijo estándar para la página real: cerrar cookies + tutorial y marcar el
# inicio del GIF. Se antepone a cualquier plan que no lo traiga.
POPUP_PREFIX: list[dict[str, Any]] = [
    {"accion": "esperar", "ms": 1000},
    {"accion": "click", "selector": ".ck-accept-btn"},
    {"accion": "esperar", "ms": 2500},
    {"accion": "click", "selector": "#tut-x"},
    {"accion": "esperar", "ms": 500},
    {"accion": "marcar"},
]

# Selectores que sabemos reales aunque el inspector no los vea (se montan
# con JS después de cargar). Patrones, no igualdad exacta.
KNOWN_SELECTOR_PATTERNS = [
    r"\.ck-accept-btn$",
    r"#tut-x$",
    r"#btn-(hiragana|katakana|kanji)(-flashcards)?$",
    r"\.btn-(quiz|write)-modal(\[data-study-type='[a-z]+'\])?$",
    r"\[data-quiz-mode='[a-z]+'\]$",
    r"\[data-auto-topic='[a-z]+'\]$",
    r"\[data-table-start='[a-z-]+'\]$",
    r"td\.kanji-clickable",
]


class ActionPlannerAgent(LLMAgent):
    """Convierte el pedido + inventario real en un plan de acciones validado.

    Tres barreras antes de aceptar un plan del modelo:
    1. Schema pydantic (ActionPlan).
    2. Normalización: acciones permitidas, esperas acotadas, prefijo popups.
    3. Chequeo semántico: cada selector debe existir en el inventario real
       o matchear la whitelist conocida. Si no, se reintenta con el motivo.
    """

    contract = AgentContract(
        id="action_planner",
        name="Action Planner",
        description="Planifica acciones Playwright validadas contra selectores reales",
        reads=("request", "url", "project", "inventory", "model"),
        writes="plan",
        output_model=ActionPlan,
        uses_llm=True,
        max_retries=2,
    )

    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    student_prompt = STUDENT_PROMPT_PATH.read_text(encoding="utf-8")

    async def execute(self, ctx: dict[str, Any]) -> ActionPlan:
        inventory_text = _inventory_text(ctx["inventory"])
        model, is_student = resolve_model(self.contract.id, ctx["model"])

        if is_student:
            # El alumno fue entrenado con el prompt compacto y el formato de
            # user exacto de dataset_builder.to_chat — hay que reproducirlo, o
            # ve entrada fuera de distribución. Emite wire; postprocess lo
            # decodifica y pasa por las MISMAS barreras que el maestro.
            system = self.student_prompt
            user = f"Pedido: {ctx['request']}\nInventario real:\n{inventory_text}"
        else:
            system = self.system_prompt
            user = f"""
Proyecto activo: {ctx["project"]["name"]}
URL real obligatoria: {ctx["url"]}
Pedido del usuario: {ctx["request"]}

INVENTARIO REAL de la página (extraído ahora mismo):
{inventory_text}

Devuelve solo JSON. No inventes una pagina local. Planea acciones para capturar la pagina real.
Si el pedido menciona un kanji concreto, intenta abrir la seccion Kanji N5 y hacer click en ese kanji.
"""
        plan, source = await self.ask_validated(model, user, ctx, system=system)
        plan.plan_source = f"student:{source}" if is_student else source
        return plan

    # ── Barrera 2: normalización ────────────────────────────────────────────
    def postprocess(self, raw: dict, ctx: dict[str, Any]) -> dict:
        # El alumno emite wire compacto ({"f","g","a":[...]}); el maestro emite
        # verboso ({"actions":[...]}). Si llega wire, se decodifica al formato
        # verboso ANTES de normalizar — así ambos pasan por las mismas barreras.
        # Decode tolerante: si faltan los nombres, la normalización los deriva
        # del pedido en vez de fallar.
        if isinstance(raw, dict) and "a" in raw and "actions" not in raw:
            try:
                decoded: dict[str, Any] = {"actions": [decode_action(a) for a in raw["a"]]}
                if raw.get("f"):
                    decoded["actions_file_name"] = raw["f"]
                if raw.get("g"):
                    decoded["gif_output_name"] = raw["g"]
                raw = decoded
            except (WireError, TypeError):
                return raw  # el schema lo rechazará y forzará reintento

        actions = raw.get("actions")
        if not isinstance(actions, list):
            return raw  # dejará que el schema lo rechace

        clean: list[dict[str, Any]] = []
        discarded = 0
        for action in actions:
            if not isinstance(action, dict) or action.get("accion") not in ALLOWED_ACTIONS:
                discarded += 1
                continue
            if action.get("accion") == "esperar":
                # Esperas absurdas (p. ej. 60000 ms) alargan el GIF sin sentido.
                action["ms"] = max(200, min(int(action.get("ms") or 1000), 8000))
            clean.append(action)

        clean, guarded = _kanji_table_guards(clean)
        discarded += guarded

        if clean and not any(a.get("accion") == "marcar" for a in clean):
            clean = POPUP_PREFIX + clean

        _ensure_min_demo(clean)

        base = _safe_name(raw.get("gif_output_name") or f"gif-{_topic_slug(ctx['request'])}.gif")
        action_file = _safe_name(raw.get("actions_file_name") or base.replace(".gif", ".json"))

        return {
            "reasoning_summary": str(raw.get("reasoning_summary") or "Plan generado por modelo."),
            "actions_file_name": action_file if action_file.endswith(".json") else action_file + ".json",
            "gif_output_name": base if base.endswith(".gif") else base + ".gif",
            "actions": clean,
            "discarded_actions": discarded,
        }

    # ── Barrera 3: selectores reales ────────────────────────────────────────
    def semantic_check(self, validated: BaseModel, ctx: dict[str, Any]) -> str:
        plan: ActionPlan = validated  # type: ignore[assignment]
        inv = ctx["inventory"]
        invalid = [
            sel
            for action in plan.actions
            if (sel := getattr(action, "selector", None)) and not _selector_allowed(sel, inv)
        ]
        if invalid:
            return (
                "Selectores que NO existen en la página real ni en la lista conocida: "
                + ", ".join(sorted(set(invalid))[:10])
                + ". Usa solo selectores del inventario o de la lista conocida."
            )
        return ""

    # ── Fallback determinista ───────────────────────────────────────────────
    def fallback(self, ctx: dict[str, Any], reason: str) -> ActionPlan:
        request = ctx["request"]
        topic = _topic_slug(request)
        kanji = extract_kanji(request)
        if kanji:
            # La tabla solo carga ~52 kanji: el pedido puede no estar visible.
            # Intentar el kanji exacto y si no está, abrir el primero — la
            # demo sigue mostrando la ficha real.
            actions = POPUP_PREFIX + [
                {"accion": "click", "selector": "#btn-kanji"},
                {"accion": "esperar", "ms": 1200},
                {"accion": "click", "selector": f"td.kanji-clickable:has-text(\"{kanji}\") >> nth=0"},
                {"accion": "click", "selector": "td.kanji-clickable >> nth=0"},
                {"accion": "esperar", "ms": 2600},
                {"accion": "clickxy", "x": 270, "y": 470},
                {"accion": "esperar", "ms": 1600},
            ]
        else:
            actions = POPUP_PREFIX + [
                {"accion": "click", "selector": "#btn-hiragana"},
                {"accion": "esperar", "ms": 1000},
                {"accion": "click", "selector": "#btn-hiragana-flashcards"},
                {"accion": "esperar", "ms": 1800},
                {"accion": "clickxy", "x": 270, "y": 450},
                {"accion": "esperar", "ms": 1600},
            ]
        return ActionPlan(
            reasoning_summary="Plan fallback seguro basado en la pagina real de Kana Trainer.",
            actions_file_name=f"acciones-{topic}.json",
            gif_output_name=f"{topic}.gif",
            actions=actions,
        )

    def repair_plan(self, request: str, run_id: str) -> ActionPlan:
        """Plan de reparación con selectores conocidos, nombres únicos por run."""
        plan = self.fallback({"request": request}, "repair")
        base = Path(plan.gif_output_name).stem
        plan.reasoning_summary = "Reparacion automatica con selectores conocidos de la pagina real."
        plan.actions_file_name = _safe_name(f"acciones-repair-{base}-{run_id}.json")
        plan.gif_output_name = _safe_name(f"repair-{base}-{run_id}.gif")
        plan.plan_source = "repair"
        return plan


BACKUP_CELL = {"accion": "click", "selector": "td.kanji-clickable >> nth=0"}

# El verifier exige >= 3.0s de GIF; pedir algo más da margen a la conversión.
MIN_DEMO_MS = 4500


def _ensure_min_demo(actions: list[dict[str, Any]]) -> None:
    """Garantiza que la demo (lo posterior a 'marcar') dure al menos
    MIN_DEMO_MS de esperas. Un plan correcto pero corto produce un GIF de
    <3s que el verifier rechaza — alargar la espera final lo evita sin
    cambiar la coreografía."""
    if not actions:
        return
    try:
        start = max(i for i, a in enumerate(actions) if a.get("accion") == "marcar") + 1
    except ValueError:
        start = 0
    demo = actions[start:]
    total = sum(int(a.get("ms") or 0) for a in demo if a.get("accion") == "esperar")
    if total >= MIN_DEMO_MS:
        return
    missing = MIN_DEMO_MS - total
    last = actions[-1]
    if last.get("accion") == "esperar" and int(last.get("ms") or 0) + missing <= 8000:
        last["ms"] = int(last.get("ms") or 0) + missing
    else:
        actions.append({"accion": "esperar", "ms": max(1000, min(missing, 8000))})


def _kanji_table_guards(actions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Guardas deterministas para la ficha de kanji — verificado contra la
    página real, no contra la obediencia del modelo:

    1. Si el plan clica una celda td.kanji-clickable, cualquier click previo
       en [data-table-start=...] o #btn-kanji-flashcards se descarta: ambos
       reemplazan la vista de tabla y las celdas dejan de existir.
    2. Tras un click td.kanji-clickable:has-text(...) se asegura el click de
       respaldo nth=0 — si el kanji exacto no está, la demo sigue mostrando
       una ficha real en vez de morir.
    """
    clicks_cell = any(
        "kanji-clickable" in (a.get("selector") or "") for a in actions
    )
    guarded: list[dict[str, Any]] = []
    discarded = 0
    for i, action in enumerate(actions):
        sel = action.get("selector") or ""
        if clicks_cell and ("data-table-start" in sel or "kanji-flashcards" in sel):
            discarded += 1
            continue
        guarded.append(action)
        if "kanji-clickable:has-text" in sel:
            nxt = actions[i + 1] if i + 1 < len(actions) else {}
            if nxt.get("selector") != BACKUP_CELL["selector"]:
                guarded.append(dict(BACKUP_CELL))
    return guarded, discarded


def _selector_allowed(selector: str, inv: dict) -> bool:
    base = selector.split(">>")[0].strip()
    for pattern in KNOWN_SELECTOR_PATTERNS:
        if re.search(pattern, base):
            return True
    if not inv.get("fetched"):
        # Sin inventario no podemos verificar: solo whitelist. Pero un id/clase
        # simple es bajo riesgo comparado con bloquear todos los planes.
        return bool(re.fullmatch(r"[#.][\w-]+", base))
    if base.startswith("#"):
        return base[1:] in inv.get("ids", [])
    if base.startswith(".") and "." not in base[1:] and "[" not in base:
        return base[1:] in inv.get("classes", [])
    if base.startswith("["):
        return base in inv.get("data_selectors", [])
    # Selectores compuestos (tag.class, :has-text…): verificar la clase raíz.
    cls = re.search(r"\.([\w-]+)", base)
    return bool(cls and cls.group(1) in inv.get("classes", []))


def _inventory_text(inv: dict) -> str:
    if not inv.get("fetched"):
        return f"(no disponible: {inv.get('note') or 'fetch falló'} — usa SOLO selectores conocidos)"
    parts = []
    if inv.get("ids"):
        parts.append("ids: " + ", ".join(f"#{i}" for i in inv["ids"][:60]))
    if inv.get("classes"):
        parts.append("clases: " + ", ".join(f".{c}" for c in inv["classes"][:60]))
    if inv.get("data_selectors"):
        parts.append("data: " + ", ".join(inv["data_selectors"][:40]))
    return "\n".join(parts) or "(página sin selectores útiles)"


def _topic_slug(text: str) -> str:
    kanji = extract_kanji(text)
    if kanji:
        return f"kanji-{ord(kanji):x}"
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (slug[:48] or "media-run").strip("-")


def extract_kanji(text: str) -> str | None:
    # La palabra 漢字 ("kanji") aparece en pedidos como "gif del 漢字 水":
    # sin quitarla, el primer match sería 漢 y no el kanji pedido.
    cleaned = text.replace("漢字", "")
    match = re.search(r"[一-鿿]", cleaned)
    return match.group(0) if match else None


def _safe_name(value: str) -> str:
    value = value.replace(" ", "-").replace("/", "-")
    value = "".join(ch if ord(ch) < 128 else f"u{ord(ch):x}" for ch in value)
    return re.sub(r"[^a-zA-Z0-9_.-]", "", value)[:120] or "artifact"
