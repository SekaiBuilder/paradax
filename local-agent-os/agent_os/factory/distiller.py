from __future__ import annotations

"""Destilación de un alumno para un agente CONSTRUIDO.

Generaliza el bucle maestro→alumno del Action Planner a cualquier agente que el
Constructor fabrique. La clave es la misma: el verificador etiqueta gratis. Para
un agente construido, el verificador es su propio contrato — si `agent.run()`
devuelve sin lanzar, la salida es schema-válida y por tanto un ejemplo
verificado. Solo esos entran al dataset.

    maestro corre el agente  →  schema válido = ejemplo verificado
        →  dataset JSONL (formato chat de mlx-lm)
        →  (LoRA fine-tune externo: train_mlx.sh — no se corre aquí)
        →  evaluar al alumno con los evals del agente  →  promover si pasa
"""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..config import DATA_DIR, DEFAULT_MODEL
from ..ollama import chat_json
from .entrenador import Entrenador
from .loader import ConstructedAgent


class TrainingExample(BaseModel):
    input: dict[str, Any]
    output: dict[str, Any]
    source: str = "master:verified"


class EvalScore(BaseModel):
    passed: int
    total: int
    score: float
    details: list[str] = []


class DistillReport(BaseModel):
    agent_id: str
    version: str
    examples: int
    dataset_path: str | None = None
    train_command: str | None = None
    ready_to_train: bool = False     # ≥ min_examples
    note: str = ""


DATASETS_DIR = DATA_DIR / "datasets"
PROMOTE_THRESHOLD = 0.95


class AgentDistiller:
    def __init__(self, entrenador: Entrenador | None = None, datasets_dir: Path | None = None):
        self.entrenador = entrenador or Entrenador()
        self.datasets_dir = datasets_dir or DATASETS_DIR
        self.datasets_dir.mkdir(parents=True, exist_ok=True)

    # ── 0. sintetizar entradas enfocadas (para afinar sobre un tema) ────────
    async def synthesize_inputs(
        self, agent: ConstructedAgent, focus: str, material_text: str = "",
        n: int = 6, model: str = DEFAULT_MODEL,
    ) -> list[dict[str, Any]]:
        """Pide al maestro entradas de ejemplo para el agente, enfocadas en un
        tema (y opcionalmente en un material). Luego el maestro las resolverá y
        el verificador (schema) filtrará — así el dataset queda centrado en el foco."""
        reads = [k for k in agent.contract.reads if k != "model"]
        if not reads:
            return []
        system = (
            "Generas ENTRADAS de ejemplo para entrenar a un agente. Devuelve SOLO "
            'JSON con la forma {"inputs": [ ... ]}, donde cada input es un objeto con '
            f"EXACTAMENTE estas claves: {', '.join(reads)}. Nada más."
        )
        user = (
            f"Agente: {agent.contract.name} — {agent.contract.description}\n"
            f"Foco del entrenamiento: {focus or '(general)'}\n"
            + (f"Material de referencia:\n{material_text[:3000]}\n" if material_text else "")
            + f"\nGenera {n} entradas variadas y realistas, centradas en el foco. Claves: {reads}."
        )
        try:
            raw = await chat_json(model, system, user)
        except Exception:
            return []
        items = raw.get("inputs") if isinstance(raw, dict) else None
        if not isinstance(items, list):
            return []
        return [it for it in items if isinstance(it, dict) and all(k in it for k in reads)][:n]

    # ── 1. generar ejemplos verificados ─────────────────────────────────────
    async def generate(self, agent: ConstructedAgent, inputs: list[dict[str, Any]]) -> list[TrainingExample]:
        """Corre el agente sobre cada input; solo los que producen salida
        schema-válida (sin excepción) entran como verificados."""
        examples: list[TrainingExample] = []
        for inp in inputs:
            try:
                out = await agent.run(dict(inp))
            except Exception:
                continue  # salida inválida → no entra (el verificador filtró gratis)
            examples.append(TrainingExample(input=inp, output=out.model_dump()))
        return examples

    # ── 2. cosechar dataset (formato chat de mlx-lm) ────────────────────────
    def to_chat_dataset(self, agent: ConstructedAgent, examples: list[TrainingExample]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for ex in examples:
            rows.append({"messages": [
                {"role": "system", "content": agent.system_prompt},
                {"role": "user", "content": agent.build_user_prompt(ex.input)},
                {"role": "assistant", "content": json.dumps(ex.output, ensure_ascii=False)},
            ]})
        return rows

    def write_dataset(self, agent_id: str, rows: list[dict[str, Any]]) -> Path:
        path = self.datasets_dir / f"{agent_id}.jsonl"
        path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + ("\n" if rows else ""),
            encoding="utf-8",
        )
        return path

    @staticmethod
    def train_command(agent_id: str, version: str, dataset_path: str | Path) -> str:
        return f"./agent_os/training/train_mlx.sh {agent_id} {version} {dataset_path}"

    # ── 3. evaluar al agente sobre sus propios evals ────────────────────────
    async def evaluate(self, agent: ConstructedAgent, evals: list[dict[str, Any]] | None = None) -> EvalScore:
        cases = evals if evals is not None else list(agent.spec.evals)
        passed = 0
        details: list[str] = []
        for i, ev in enumerate(cases):
            ctx = dict(ev.get("input") or {})
            try:
                out = await agent.run(ctx)
            except Exception as exc:
                details.append(f"#{i} ✗ {str(exc)[:80]}")
                continue
            expect = ev.get("expect") or {}
            if _matches(expect, out.model_dump(), agent):
                passed += 1
                details.append(f"#{i} ✓")
            else:
                details.append(f"#{i} ✗ no cumple expect")
        total = len(cases)
        return EvalScore(passed=passed, total=total, score=(passed / total if total else 1.0), details=details)

    # ── 4. orquestar: generar → dataset → (entrenar fuera) ──────────────────
    async def distill(
        self, agent: ConstructedAgent, inputs: list[dict[str, Any]], version: str = "v1", min_examples: int = 100
    ) -> DistillReport:
        examples = await self.generate(agent, inputs)
        rows = self.to_chat_dataset(agent, examples)
        path = self.write_dataset(agent.contract.id, rows)
        ready = len(examples) >= min_examples
        return DistillReport(
            agent_id=agent.contract.id,
            version=version,
            examples=len(examples),
            dataset_path=str(path),
            train_command=self.train_command(agent.contract.id, version, path),
            ready_to_train=ready,
            note="apto para entrenar" if ready else f"necesita ≥{min_examples} ejemplos verificados (tiene {len(examples)})",
        )

    async def promote_if_ready(
        self, agent: ConstructedAgent, student_model: str, threshold: float = PROMOTE_THRESHOLD
    ) -> dict[str, Any]:
        """Promueve al alumno SOLO si pasa los evals del agente — el mismo umbral
        del pipeline. La promoción la hace el Entrenador (escribe models.json)."""
        score = await self.evaluate(agent)
        if score.score >= threshold:
            self.entrenador.promote(agent.contract.id, student_model)
            return {"promoted": True, "model": student_model, "score": score.score}
        return {"promoted": False, "score": score.score, "threshold": threshold}


def _matches(expect: dict[str, Any], output: dict[str, Any], agent: ConstructedAgent) -> bool:
    """`expect` flexible: {"writes": "x"} comprueba el contrato; cualquier otra
    clave se compara contra el campo homónimo de la salida."""
    for key, want in expect.items():
        if key == "writes":
            if agent.contract.writes != want:
                return False
        elif output.get(key) != want:
            return False
    return True
