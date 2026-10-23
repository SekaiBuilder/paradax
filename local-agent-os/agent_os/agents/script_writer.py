from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.agent import LLMAgent
from ..core.contract import AgentContract
from ..core.schemas import VoiceScript
from .action_planner import extract_kanji

PROMPT_PATH = Path(__file__).parent / "prompts" / "script_writer.md"

VOICE_DEFAULTS = {
    "es": "こんにちは皆さん. Mira como Kana Trainer te ayuda a practicar japonés en su página real. Pruébala gratis, enlace en la bio.",
    "en": "こんにちは皆さん. See how Kana Trainer helps you practice Japanese on the real page. Try it free, link in bio.",
    "it": "こんにちは皆さん. Guarda come Kana Trainer ti aiuta a praticare il giapponese sulla pagina reale. Provala gratis, link in bio.",
}

KANJI_TEMPLATES = {
    "es": "こんにちは皆さん. Hoy vemos el 漢字 {k} en la página real de Kana Trainer. Mira su lectura, significado y ejemplos. Pruébala gratis, enlace en la bio.",
    "en": "こんにちは皆さん. Today we look at the 漢字 {k} on the real Kana Trainer page. See its reading, meaning and examples. Try it free, link in bio.",
    "it": "こんにちは皆さん. Oggi vediamo il 漢字 {k} sulla pagina reale di Kana Trainer. Guarda lettura, significato ed esempi. Provala gratis, link in bio.",
}


class ScriptWriterAgent(LLMAgent):
    """Escribe el guion de voz del reel en el idioma pedido."""

    contract = AgentContract(
        id="script_writer",
        name="Script Writer",
        description="Escribe guiones de voz cortos para reels en el idioma pedido",
        reads=("request", "language", "model"),
        writes="voice",
        output_model=VoiceScript,
        uses_llm=True,
        max_retries=1,
    )

    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    async def execute(self, ctx: dict[str, Any]) -> VoiceScript:
        user = f"""
Idioma del guion: {ctx["language"]}
Pedido del usuario: {ctx["request"]}

Devuelve solo el JSON con voice_script.
"""
        script, source = await self.ask_validated(ctx["model"], user, ctx)
        script.source = source
        return script

    def postprocess(self, raw: dict, ctx: dict[str, Any]) -> dict:
        text = raw.get("voice_script") or raw.get("text") or raw.get("script") or ""
        return {"language": ctx["language"], "text": str(text).strip()}

    def fallback(self, ctx: dict[str, Any], reason: str) -> VoiceScript:
        lang = ctx["language"]
        kanji = extract_kanji(ctx["request"])
        if kanji and lang in KANJI_TEMPLATES:
            text = KANJI_TEMPLATES[lang].format(k=kanji)
        else:
            text = VOICE_DEFAULTS.get(lang, VOICE_DEFAULTS["es"])
        return VoiceScript(language=lang, text=text)
