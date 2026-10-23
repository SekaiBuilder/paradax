from __future__ import annotations

"""Agente fantasma: la salida de emergencia de la fábrica.

Se activa SOLO cuando el Validador falla un build. Lo que hace: una llamada por
el terminal de Claude Code en modo headless (`claude -p`) para que aporte lo que
el Constructor local no pudo — típicamente una skill/herramienta que no existía.

GUARDARRAÍL INNEGOCIABLE
------------------------
El fantasma NUNCA aplica nada solo y NUNCA ejecuta el código que recibe. Todo
lo que trae de Claude Code se **stagea** (escribe a `data/ghost_staging/`) con
estado `pending`. Solo una aprobación humana explícita (`approve`) lo promueve
al Skill Master. Esta es la única parte del sistema que puede romper algo de
verdad; por eso esa puerta se cierra con llave.
"""

import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from ..config import DATA_DIR
from .skill import Skill
from .skill_master import SkillMaster
from .tool_catalog import ToolDef, register_tool

STAGING_DIR = DATA_DIR / "ghost_staging"
# El código de tools propuesto por Claude Code se escribe aquí para REVISIÓN
# HUMANA. Nada de esto se importa ni se ejecuta automáticamente.
GENERATED_TOOLS_DIR = Path(__file__).parent / "generated_tools"

# Llamada a Claude Code inyectable: (prompt) -> texto de salida. Por defecto, el
# subproceso real `claude -p`. Los tests inyectan una falsa (nada de red/CLI).
CallClaude = Callable[[str], Awaitable[str]]


class GhostError(RuntimeError):
    pass


class StagedProposal(BaseModel):
    id: str
    request: str
    failure_reason: str
    skill: dict[str, Any]                 # skill/tool propuesta (datos), aún sin aplicar
    needs_human_code: bool = False        # True si Claude Code propuso una tool (código)
    status: str = "pending"               # pending | approved | rejected
    created_at: float = Field(default_factory=time.time)
    # Solo cuando needs_human_code: la herramienta propuesta (para revisión humana).
    tool_name: str = ""
    tool_signature: str = ""
    tool_code: str = ""


class Ghost:
    def __init__(self, call_claude: CallClaude | None = None, staging: Path | None = None):
        self._call = call_claude or _real_claude
        self.staging = staging or STAGING_DIR
        self.staging.mkdir(parents=True, exist_ok=True)

    # ── escalada ──────────────────────────────────────────────────────────────
    async def escalate(self, request: str, failure_reason: str, missing: str = "") -> StagedProposal:
        """Pide a Claude Code la skill que falta y la DEJA EN STAGING (no la aplica)."""
        prompt = _build_prompt(request, failure_reason, missing)
        raw = await self._call(prompt)
        skill_dict = _extract_skill(raw)
        needs_code = bool(skill_dict.get("kind") == "tool" or skill_dict.get("needs_human_code"))
        proposal = StagedProposal(
            id=f"ghost-{_slug(request)}-{uuid.uuid4().hex[:6]}",
            request=request,
            failure_reason=failure_reason,
            skill=skill_dict,
            needs_human_code=needs_code,
        )
        if needs_code:
            proposal.tool_name = str(skill_dict.get("name") or skill_dict.get("id") or "")
            proposal.tool_signature = str(skill_dict.get("signature") or "")
            proposal.tool_code = str(skill_dict.get("implementation") or skill_dict.get("code") or "")
        self._write(proposal)
        return proposal

    # ── cola de aprobación ──────────────────────────────────────────────────────
    def pending(self) -> list[StagedProposal]:
        out: list[StagedProposal] = []
        for path in sorted(self.staging.glob("*.json")):
            try:
                p = StagedProposal.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if p.status == "pending":
                out.append(p)
        return out

    def get(self, proposal_id: str) -> StagedProposal | None:
        path = self.staging / f"{proposal_id}.json"
        if not path.exists():
            return None
        try:
            return StagedProposal.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def approve(self, proposal_id: str, skill_master: SkillMaster) -> Skill:
        """Promueve una propuesta al Skill Master. SOLO tras revisión humana.

        Si la propuesta requiere código nuevo (una tool), no se ejecuta nada: se
        rechaza la auto-aplicación y se exige que un humano implemente la tool.
        """
        proposal = self.get(proposal_id)
        if proposal is None:
            raise GhostError(f"propuesta no encontrada: {proposal_id}")
        if proposal.needs_human_code:
            raise GhostError(
                "esta propuesta requiere código nuevo (una tool); impleméntala y "
                "regístrala en el catálogo a mano — el fantasma no ejecuta código."
            )
        skill = Skill.model_validate({**proposal.skill, "created_by": "ghost"})
        skill_master.add(skill)
        proposal.status = "approved"
        self._write(proposal)
        return skill

    def reject(self, proposal_id: str) -> bool:
        proposal = self.get(proposal_id)
        if proposal is None:
            return False
        proposal.status = "rejected"
        self._write(proposal)
        return True

    # ── propuestas de TOOL (código) ─────────────────────────────────────────────
    def pending_tools(self) -> list[StagedProposal]:
        return [p for p in self.pending() if p.needs_human_code]

    def approve_tool(self, proposal_id: str, tools_dir: Path | None = None) -> dict[str, Any]:
        """Aprueba una tool propuesta: escribe su código a `generated_tools/`
        PARA REVISIÓN HUMANA y registra su metadata en el catálogo (sube el techo
        del Constructor). NO importa ni ejecuta el código — wirearlo a ejecución
        es un paso humano aparte, deliberado."""
        proposal = self.get(proposal_id)
        if proposal is None:
            raise GhostError(f"propuesta no encontrada: {proposal_id}")
        if not proposal.needs_human_code:
            raise GhostError("esta propuesta es una skill (datos); usa approve, no approve_tool")
        name = re.sub(r"[^a-z0-9_]", "_", (proposal.tool_name or "tool").lower()).strip("_") or "tool"
        if not proposal.tool_code.strip():
            raise GhostError("la propuesta no trae código de implementación")

        out_dir = tools_dir or GENERATED_TOOLS_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{name}.py"
        header = (
            "# GENERADO POR EL AGENTE FANTASMA — revisar antes de integrar.\n"
            "# NO se importa ni se ejecuta automáticamente. Revísalo y wirealo a mano.\n"
            f"# Propuesta: {proposal.id} · firma sugerida: {proposal.tool_signature or 'n/d'}\n\n"
        )
        path.write_text(header + proposal.tool_code + "\n", encoding="utf-8")

        # Solo metadata al catálogo: el Constructor podrá componer con esta tool;
        # la ejecución real requiere que un humano la conecte.
        register_tool(ToolDef(
            name=name,
            description=str(proposal.skill.get("description") or "tool propuesta por el fantasma"),
            signature=proposal.tool_signature or f"{name}(...)",
        ))
        proposal.status = "approved"
        self._write(proposal)
        return {"tool": name, "path": str(path), "registered": True, "executed": False}

    def _write(self, proposal: StagedProposal) -> None:
        (self.staging / f"{proposal.id}.json").write_text(
            proposal.model_dump_json(indent=2), encoding="utf-8"
        )


# ── helpers ──────────────────────────────────────────────────────────────────
def _build_prompt(request: str, failure_reason: str, missing: str) -> str:
    return (
        "Eres un experto ayudando a la fábrica de agentes de Paradax. El Constructor "
        "local no pudo cubrir esta necesidad y el Validador falló.\n\n"
        f"Necesidad: {request}\n"
        f"Motivo del fallo: {failure_reason}\n"
        f"Lo que parece faltar: {missing or '(no especificado)'}\n\n"
        "Propón UNA skill reutilizable que resuelva el hueco. Devuelve SOLO un JSON con: "
        "id (kebab), name, kind (capability|prompt|tool|eval|schema), description, "
        "tags (lista), prompt (instrucciones). Si hace falta una herramienta NUEVA de "
        "código, pon kind='tool' y añade 'signature' (firma de la función Python) e "
        "'implementation' (el código Python de la función). No expliques nada fuera del JSON."
    )


def _extract_skill(raw: str) -> dict[str, Any]:
    """Tolerante: acepta el JSON directo, el envelope de `--output-format json`,
    o un bloque JSON embebido en texto."""
    raw = raw.strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "result" in data and isinstance(data["result"], str):
            return _extract_skill(data["result"])  # envelope de claude
        if isinstance(data, dict) and data.get("id"):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict) and data.get("id"):
                return data
        except json.JSONDecodeError:
            pass
    raise GhostError(f"Claude Code no devolvió una skill JSON válida: {raw[:300]}")


def _slug(text: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:24]) or "gap"


async def _real_claude(prompt: str) -> str:
    """Subproceso real `claude -p … --output-format json`. Forzamos un modelo
    disponible (el default del CLI puede estar caído, p. ej. Fable 5)."""
    import os
    model = os.getenv("PARADAX_CLAUDE_MODEL", "sonnet")
    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", prompt, "--output-format", "json", "--model", model,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    text = out.decode(errors="replace")
    if proc.returncode != 0:
        raise GhostError(f"claude -p falló: {err.decode(errors='replace')[:400] or text[:300]}")
    try:
        env = json.loads(text)
        if isinstance(env, dict) and env.get("is_error"):
            raise GhostError(f"claude error: {str(env.get('result'))[:300]}")
    except json.JSONDecodeError:
        pass
    return text
