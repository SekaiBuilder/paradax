from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..config import DATA_DIR

PROJECTS_DIR = DATA_DIR / "projects"

ProjectStatus = Literal["draft", "planning", "building", "ready", "failed"]
TaskStatus = Literal["pending", "running", "completed", "blocked", "failed"]


class ProjectTask(BaseModel):
    id: str
    request: str
    status: TaskStatus = "pending"
    run_id: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class Project(BaseModel):
    """Un proyecto: un objetivo para el que la fábrica construye un equipo de
    agentes. El Project Manager lo escucha y lo lleva de 'draft' a 'ready'."""

    id: str
    name: str
    goal: str = ""
    description: str = ""
    status: ProjectStatus = "draft"

    agents: list[str] = Field(default_factory=list)        # ids de agentes creados para el proyecto
    team_plan: dict[str, Any] | None = None                # salida del Team Planner
    briefs: list[dict[str, Any]] = Field(default_factory=list)  # salida del Skills Definer
    inputs: dict[str, Any] = Field(default_factory=dict)    # contexto semilla del proyecto (lo que no produce ningún agente)
    tasks: list[ProjectTask] = Field(default_factory=list)  # solicitudes ejecutables desde el chat
    log: list[str] = Field(default_factory=list)           # bitácora legible del PM
    # Modo de ejecución del pipeline: False = manual (botón ▶ / chat),
    # True = automático (el pipeline corre solo al quedar el equipo listo).
    auto_run: bool = False
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def note(self, msg: str) -> None:
        self.log.append(msg)
        self.updated_at = time.time()

    def add_task(self, request: str) -> ProjectTask:
        task = ProjectTask(id=f"task-{int(time.time() * 1000)}", request=request)
        self.tasks.append(task)
        self.updated_at = time.time()
        return task

    def update_task(
        self,
        task_id: str,
        *,
        status: TaskStatus | None = None,
        run_id: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> ProjectTask | None:
        for task in self.tasks:
            if task.id != task_id:
                continue
            if status is not None:
                task.status = status
            if run_id is not None:
                task.run_id = run_id
            if result is not None:
                task.result = result
            if error is not None:
                task.error = error
            task.updated_at = time.time()
            self.updated_at = time.time()
            return task
        return None


def slug(text: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40]) or "proyecto"


class ProjectStore:
    def __init__(self, root: Path | None = None):
        self.root = root or PROJECTS_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        self._projects: dict[str, Project] = {}
        self._load()

    def _load(self) -> None:
        self._projects.clear()
        for path in sorted(self.root.glob("*.json")):
            try:
                p = Project.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            self._projects[p.id] = p

    def _path(self, project_id: str) -> Path:
        return self.root / f"{project_id}.json"

    def save(self, project: Project) -> Project:
        project.updated_at = time.time()
        self._projects[project.id] = project
        self._path(project.id).write_text(project.model_dump_json(indent=2), encoding="utf-8")
        return project

    def create(self, name: str, goal: str = "", description: str = "") -> Project:
        base = slug(name)
        pid = base
        i = 2
        while pid in self._projects:
            pid = f"{base}-{i}"
            i += 1
        project = Project(id=pid, name=name, goal=goal or name, description=description)
        project.note("proyecto creado")
        return self.save(project)

    def get(self, project_id: str) -> Project | None:
        return self._projects.get(project_id)

    def all(self) -> list[Project]:
        return sorted(self._projects.values(), key=lambda p: p.created_at)

    def remove(self, project_id: str) -> bool:
        existed = self._projects.pop(project_id, None) is not None
        path = self._path(project_id)
        if path.exists():
            path.unlink()
        return existed
