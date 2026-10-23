from __future__ import annotations

"""Jerarquías: grafo editable global, grafo del sistema y organigrama por proyecto."""

import json

from fastapi import APIRouter, HTTPException

from ...config import ensure_dirs
from ...factory import system_agents as sysagents
from .. import org_chart
from ..state import (
    DEFAULT_HIERARCHY, HIERARCHY_FILE, PM,
    _with_dynamic_nodes,
)

router = APIRouter()


@router.get("/api/hierarchy")
def get_hierarchy(project: str | None = None):
    # El pipeline de MEDIA MANAGER (los agentes REGISTRY) ya NO es "principal":
    # solo aparece bajo el grupo 'media-manager' (o en 'all'). El global y los
    # demás proyectos no lo muestran — el global queda para lo que no es dominio.
    if project in ("media-manager", "all"):
        base = json.loads(HIERARCHY_FILE.read_text(encoding="utf-8")) if HIERARCHY_FILE.exists() else DEFAULT_HIERARCHY
    else:
        base: dict = {"agents": [], "edges": []}
    return _with_dynamic_nodes(base, project)


@router.get("/api/system/agents")
def system_agents_graph():
    """Los agentes de sistema de Paradax y su grafo de interacciones (separado
    de los agentes de proyecto). Incluye banderas contactable / on_demand."""
    return sysagents.graph()


@router.put("/api/hierarchy")
def save_hierarchy(data: dict):
    ensure_dirs()
    HIERARCHY_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"ok": True}


@router.get("/api/projects/{project_id}/org")
def project_org(project_id: str):
    """Organigrama del proyecto: Project Manager → Team Constructor →
    Orquestador → agentes que deciden → agentes que ejecutan."""
    project = None
    if project_id != "media-manager":
        project = PM.store.get(project_id)
        if not project:
            raise HTTPException(status_code=404, detail="proyecto no encontrado")
    return org_chart.build(project_id, project)
