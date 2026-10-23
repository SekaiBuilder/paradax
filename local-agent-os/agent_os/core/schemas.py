from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ActionKind = Literal[
    "esperar", "click", "escribir", "tipear", "scroll", "hover", "tecla", "clickxy", "ir", "marcar"
]


class Action(BaseModel):
    """Una acción Playwright del recorder. Campos extra (selector, ms, x, y,
    texto…) se conservan tal cual — el recorder JS los consume."""

    model_config = ConfigDict(extra="allow")
    accion: ActionKind


class SelectorInventory(BaseModel):
    """Inventario de selectores REALES extraídos de la página."""

    url: str
    fetched: bool
    ids: list[str] = Field(default_factory=list)
    classes: list[str] = Field(default_factory=list)
    data_selectors: list[str] = Field(default_factory=list)
    note: str = ""


class ActionPlan(BaseModel):
    """Plan de acciones validado para el Browser Recorder."""

    reasoning_summary: str
    actions_file_name: str
    gif_output_name: str
    actions: list[Action] = Field(min_length=1)
    plan_source: str = "model"
    discarded_actions: int = 0


class VoiceScript(BaseModel):
    language: str
    text: str = Field(min_length=10)
    source: str = "model"


class MediaVerification(BaseModel):
    model_config = ConfigDict(extra="allow")
    exists: bool
    path: str
    duration: float
    size: int
    ok: bool


class GifResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    path: str
    verification: MediaVerification
    failed_steps: int = 0


class ReelResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    path: str
    verification: MediaVerification


class Verdict(BaseModel):
    """Salida del Verifier: apto o no, y por qué."""

    ok: bool
    target: str
    reason: str = ""
    should_repair: bool = False
