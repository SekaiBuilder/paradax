from __future__ import annotations

"""Skill Master: la memoria de skills de la fábrica.

Guarda cada skill en formato compacto skill-wire (`<id>.skw`, JSON de la forma
compacta) bajo `data/skills/`. Es el órgano del que el Constructor saca las
capacidades relevantes a un proyecto, y al que el Entrenador (vía ejemplos
exitosos) y el agente fantasma (vía Claude Code) devuelven skills nuevas —
subiendo el techo del Constructor.

El Constructor solo COMPONE desde aquí: nunca inventa una capacidad que no
exista en el Skill Master.
"""

import json
from pathlib import Path
from typing import Any

from ..config import DATA_DIR
from .skill import Skill
from .skill_wire import SkillWireError

SKILLS_DIR = DATA_DIR / "skills"


class SkillMaster:
    def __init__(self, root: Path | None = None):
        self.root = root or SKILLS_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        self._skills: dict[str, Skill] = {}
        self._load()

    # ── persistencia ────────────────────────────────────────────────────────
    def _load(self) -> None:
        self._skills.clear()
        for path in sorted(self.root.glob("*.skw")):
            try:
                compact = json.loads(path.read_text(encoding="utf-8"))
                skill = Skill.from_wire(compact)
            except (json.JSONDecodeError, SkillWireError, ValueError, OSError):
                continue  # un archivo corrupto no debe tumbar toda la memoria
            self._skills[skill.id] = skill

    def _path(self, skill_id: str) -> Path:
        return self.root / f"{skill_id}.skw"

    # ── escritura ─────────────────────────────────────────────────────────────
    def add(self, skill: Skill) -> Path:
        """Añade (o reemplaza) una skill, persistida en formato compacto."""
        self._skills[skill.id] = skill
        path = self._path(skill.id)
        path.write_text(
            json.dumps(skill.to_wire(), ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        return path

    def remove(self, skill_id: str) -> bool:
        existed = self._skills.pop(skill_id, None) is not None
        path = self._path(skill_id)
        if path.exists():
            path.unlink()
        return existed

    # ── lectura ───────────────────────────────────────────────────────────────
    def get(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def __len__(self) -> int:
        return len(self._skills)

    def query(
        self,
        text: str | None = None,
        tags: list[str] | None = None,
        kind: str | None = None,
        limit: int = 10,
    ) -> list[Skill]:
        """Devuelve las skills más relevantes a un proyecto, rankeadas.

        Relevancia simple y explicable (no un embedding opaco): solape de tags
        (peso fuerte) + coincidencia de texto en nombre/descripción/prompt/tags.
        Es justo lo que el Constructor necesita para componer un agente.
        """
        wanted_tags = {t.lower() for t in (tags or [])}
        needle = (text or "").lower().strip()
        terms = [w for w in needle.split() if w]

        scored: list[tuple[float, Skill]] = []
        for skill in self._skills.values():
            if kind and skill.kind != kind:
                continue
            score = 0.0
            skill_tags = {t.lower() for t in skill.tags}
            score += 3.0 * len(wanted_tags & skill_tags)
            haystack = " ".join(
                [skill.name, skill.description, skill.prompt, " ".join(skill.tags)]
            ).lower()
            for term in terms:
                if term in haystack:
                    score += 1.0
            # Sin señales de ranking (ni tags ni texto) no filtramos por
            # relevancia: devolvemos todo lo que pasó el guard de kind.
            if score > 0 or (not wanted_tags and not terms):
                scored.append((score, skill))

        scored.sort(key=lambda pair: (-pair[0], pair[1].id))
        return [skill for _score, skill in scored[:limit]]

    # ── métricas ──────────────────────────────────────────────────────────────
    def stats(self) -> dict[str, Any]:
        by_kind: dict[str, int] = {}
        verbose_bytes = compact_bytes = 0
        for skill in self._skills.values():
            by_kind[skill.kind] = by_kind.get(skill.kind, 0) + 1
            verbose_bytes += len(json.dumps(skill.model_dump(), ensure_ascii=False))
            compact_bytes += len(json.dumps(skill.to_wire(), ensure_ascii=False, separators=(",", ":")))
        ratio = round(verbose_bytes / compact_bytes, 2) if compact_bytes else 0.0
        return {
            "count": len(self._skills),
            "by_kind": by_kind,
            "verbose_bytes": verbose_bytes,
            "compact_bytes": compact_bytes,
            "compression": ratio,
        }


if __name__ == "__main__":
    import tempfile

    sm = SkillMaster(root=Path(tempfile.mkdtemp()) / "skills")
    sm.add(Skill(
        id="web-selectors", name="Selectores reales", kind="capability",
        description="Extrae ids/clases reales y planifica solo con ellos.",
        tags=["web", "selectores", "playwright"], tools=["http_get"],
        prompt="Usa SOLO selectores del inventario real.",
    ))
    sm.add(Skill(
        id="voice-script-es", name="Guion de voz (es)", kind="prompt",
        description="Escribe un guion de locución corto en español latino.",
        tags=["media", "tts", "español"],
        prompt="Abre con «¡Konnichiwa minna-san!» y cierra con un CTA.",
    ))
    sm.add(Skill(
        id="hard-verify", name="Verificación dura", kind="eval",
        description="Pasa/repara con ffprobe: duración mínima, 0 pasos fallidos.",
        tags=["media", "verificacion"],
        evals=[{"input": "gif de 1s", "expect": "reparar"}],
    ))

    print("skills en memoria:", len(sm))
    print("query 'web' →", [s.id for s in sm.query(text="web página")])
    print("query tags media →", [s.id for s in sm.query(tags=["media"])])
    print("stats:", sm.stats())
    # reload from disk → la memoria persiste y se reconstruye desde compacto
    sm2 = SkillMaster(root=sm.root)
    print("recargado desde disco:", len(sm2), "→", sorted(s.id for s in sm2.all()))
