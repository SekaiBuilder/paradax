from __future__ import annotations

"""Entrenador (pilar 2) como órgano de primera clase.

La mecánica pesada ya existe en `agent_os/training/` (generator, dataset_builder,
evaluator, train_mlx). Esta fachada le da una interfaz limpia y una superficie
para el control center: qué agentes tienen alumno propio promocionado, la receta
de entrenamiento por agente, y las acciones de promover/degradar.

Destilación maestro→alumno: el maestro (30B) planifica, el Verifier etiqueta
gratis (solo runs verificados sin reparación), un Qwen pequeño aprende la tarea.
"""

import json
from pathlib import Path
from typing import Any

from ..config import DATA_DIR, DEFAULT_MODEL
from .readers import DocReaderAgent, Material, UrlReaderAgent

MODELS_FILE = DATA_DIR / "models.json"
TRAINING_QUEUE_DIR = DATA_DIR / "training_queue"


class Entrenador:
    def __init__(self, models_file: Path | None = None):
        self.models_file = models_file or MODELS_FILE
        # Colaboradores durmientes: solo el Entrenador los invoca.
        self.doc_reader = DocReaderAgent()
        self.url_reader = UrlReaderAgent()

    # ── estado ────────────────────────────────────────────────────────────────
    def models_map(self) -> dict[str, str]:
        try:
            return json.loads(self.models_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def status(self, agent_id: str, fallback: str = DEFAULT_MODEL) -> dict[str, Any]:
        mapping = self.models_map()
        model = mapping.get(agent_id)
        is_student = bool(model)
        return {
            "agent_id": agent_id,
            "active_model": str(model) if is_student else fallback,
            "specialized": is_student,
            "engine": "alumno propio" if is_student else "maestro",
        }

    def roster(self, agent_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """Estado de cada agente LLM. Si no se pasan ids, usa el REGISTRY vivo."""
        if agent_ids is None:
            agent_ids = self._live_llm_agent_ids()
        return [self.status(aid) for aid in agent_ids]

    def _live_llm_agent_ids(self) -> list[str]:
        ids: list[str] = []
        try:
            from ..agents import REGISTRY
            ids += [a.contract.id for a in REGISTRY.values() if a.contract.uses_llm]
        except Exception:
            pass
        try:
            from .loader import DYNAMIC
            ids += [a.contract.id for a in DYNAMIC.all() if a.contract.uses_llm]
        except Exception:
            pass
        return ids

    # ── material (vía colaboradores durmientes) ─────────────────────────────────
    def collaborators(self) -> list[dict[str, Any]]:
        """Los dos lectores, para el grafo de interacciones. Durmientes y no
        contactables: se ven, pero nadie habla con ellos salvo el Entrenador."""
        return [self.doc_reader.contract.summary(), self.url_reader.contract.summary()]

    async def ingest_material(self, source: str) -> Material:
        """Despierta al colaborador adecuado para leer material de entrenamiento.
        URL → Lector de URLs · PDF/archivo de texto → Lector de documentos."""
        if source.strip().lower().startswith(("http://", "https://")):
            return await self.url_reader.run({"url": source})
        return await self.doc_reader.run({"source": source})

    async def refine(self, agent: Any, focus: str = "", material_source: str | None = None) -> dict[str, Any]:
        """Envía un agente a afinar sus skills sobre algo específico. Si hay
        material (URL/PDF), despierta al colaborador lector para leerlo. Encola
        la petición con la receta de entrenamiento (el fine-tune real es externo)."""
        material = None
        if material_source:
            m = await self.ingest_material(material_source)
            material = {"source": m.source, "kind": m.kind, "chars": m.chars, "preview": m.text[:200]}
        spec = getattr(agent, "spec", None)
        brief = {
            "agent_id": agent.contract.id,
            "agent_name": agent.contract.name,
            "focus": focus,
            "skills": list(spec.skills) if spec else [],
            "material": material,
            "plan": self.training_plan(agent.contract.id, "v1"),
            "status": "queued",
        }
        TRAINING_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        (TRAINING_QUEUE_DIR / f"{agent.contract.id}.json").write_text(
            json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return brief

    def training_queue(self) -> list[dict[str, Any]]:
        if not TRAINING_QUEUE_DIR.exists():
            return []
        out = []
        for p in sorted(TRAINING_QUEUE_DIR.glob("*.json")):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
        return out

    def dequeue(self, agent_id: str) -> bool:
        path = TRAINING_QUEUE_DIR / f"{agent_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    async def run_training(self, agent: Any, model: str = DEFAULT_MODEL, n: int = 6) -> dict[str, Any]:
        """Dispara la destilación de verdad para un agente encolado: sintetiza
        entradas enfocadas (foco + material), las resuelve con el maestro, el
        schema verifica, y produce el dataset. El fine-tune LoRA sigue siendo
        el paso externo (train_mlx.sh), cuyo comando se devuelve."""
        from .distiller import AgentDistiller

        brief = next((b for b in self.training_queue() if b["agent_id"] == agent.contract.id), None)
        if brief is None:
            raise ValueError(f"no hay petición encolada para '{agent.contract.id}'")

        material_text = ""
        src = (brief.get("material") or {}).get("source")
        if src:
            material_text = (await self.ingest_material(src)).text

        distiller = AgentDistiller(entrenador=self)
        inputs = await distiller.synthesize_inputs(agent, brief.get("focus", ""), material_text, n=n, model=model)
        report = await distiller.distill(agent, inputs, min_examples=max(1, (len(inputs) + 1) // 2))

        brief["status"] = "dataset-listo" if report.examples else "sin-ejemplos"
        brief["dataset"] = {
            "inputs_sintetizados": len(inputs),
            "ejemplos_verificados": report.examples,
            "path": report.dataset_path,
            "train_command": report.train_command,
        }
        (TRAINING_QUEUE_DIR / f"{agent.contract.id}.json").write_text(
            json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return brief

    # ── receta ────────────────────────────────────────────────────────────────
    def training_plan(self, agent_id: str, version: str = "v1") -> list[dict[str, str]]:
        """Los pasos para destilar un alumno de este agente — como comandos."""
        return [
            {"step": "generar", "cmd": f"python -m agent_os.training.generator --rounds 200"},
            {"step": "cosechar", "cmd": "python -m agent_os.training.dataset_builder"},
            {"step": "entrenar", "cmd": f"./agent_os/training/train_mlx.sh {version}"},
            {"step": "evaluar", "cmd": f"python -m agent_os.training.evaluator --model agent-os/{agent_id}:{version} --promote"},
        ]

    # ── acciones ────────────────────────────────────────────────────────────────
    def promote(self, agent_id: str, model: str) -> dict[str, str]:
        """Marca un alumno como activo para un agente (lo que hace evaluator --promote).
        En producción cada agente lo resolverá solo vía resolve_model."""
        mapping = self.models_map()
        mapping[agent_id] = model
        self._write(mapping)
        return mapping

    def demote(self, agent_id: str) -> dict[str, str]:
        mapping = self.models_map()
        mapping.pop(agent_id, None)
        self._write(mapping)
        return mapping

    def _write(self, mapping: dict[str, str]) -> None:
        self.models_file.parent.mkdir(parents=True, exist_ok=True)
        self.models_file.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
