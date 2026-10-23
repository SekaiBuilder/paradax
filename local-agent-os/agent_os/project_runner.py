from __future__ import annotations

"""Ejecuta el PIPELINE de un proyecto (no solo construir el equipo: correrlo).

- Proyectos con runner dedicado (PROJECT_RUNNERS) usan su orquestador real
  (registrados en PROJECT_RUNNERS por id de proyecto).
- El resto cae a un runner genérico: corre los agentes del proyecto en orden
  sobre un contexto compartido (best-effort; los que les falten claves se saltan).

Emite eventos al BUS para el panel de actividad en vivo, y registra el run en SQLite.
"""

import asyncio
import uuid
from typing import Any, Awaitable, Callable

from . import db
from .config import DEFAULT_MODEL, PARADAX_ROOT
from .core.events import BUS
from .core.pipeline import Pipeline
from .factory.loader import DYNAMIC
from .factory.spec import effective_tier
from .factory.tool_runtime import DEFAULT_RUNTIME, SANDBOX_AGENT_ID_VAR, SANDBOX_BUS_VAR, SANDBOX_RUN_ID_VAR


# Registro de orquestadores por proyecto. Añade aquí los que tengan pipeline propio.
PROJECT_RUNNERS: dict[str, Callable[[str], Awaitable[dict[str, Any]]]] = {
}

_MESSAGE_KEYS = {
    "task_request",
    "request",
    "message",
    "prompt",
    "feature_request",
    "requirements",
    "requerimientos",
    "need",
    "objective",
    "objetivo",
    "tema",
    "topic",
    "consulta",
}
_PROJECT_CONTEXT_KEYS = {"project_context", "context", "contexto", "project_goal"}
_WORKSPACE_KEYS = {"workspace_root", "codebase_path", "codigo_fuente"}
_WORKSPACE_MAP_KEYS = {"workspace_map", "project_map", "codigo_mapa"}


def task_inputs(project: Any, request: str) -> dict[str, Any]:
    """Traduce un mensaje humano a claves semilla para el equipo del proyecto.

    No inventa URLs ni credenciales REALES. Rellena claves de texto comunes, el
    contexto del proyecto y la ruta local de Paradax; y para las claves que el
    Constructor inventó y nadie produce (p.ej. 'system_config'), le pasa el
    encargo al agente en texto — el agente es un LLM y deriva el valor él mismo.
    Sin esto, un solo read huérfano bloqueaba el pipeline entero para siempre.
    """
    seed = dict(getattr(project, "inputs", {}) or {})
    # Las claves de PETICIÓN reflejan SIEMPRE la tarea actual: un feature_request
    # viejo guardado en project.inputs NO debe pisar lo que el usuario pide ahora.
    for k in _MESSAGE_KEYS:
        seed.pop(k, None)
    required = _required_seed_keys(project)

    for key in required:
        if key in _MESSAGE_KEYS:
            seed[key] = request
        elif key in seed:
            continue
        elif key in _PROJECT_CONTEXT_KEYS:
            seed[key] = _project_context(project)
        elif key in _WORKSPACE_KEYS:
            seed[key] = str(PARADAX_ROOT)
        elif key in _WORKSPACE_MAP_KEYS:
            seed[key] = _workspace_map()
        else:
            # Clave huérfana: nadie la produce y el usuario no la rellenó.
            # Se desbloquea el plan pasándole el encargo al agente.
            seed[key] = (
                f"(no hay un valor explícito para '{key}' — derívalo tú a partir "
                f"del encargo) Petición: {request}. Objetivo del proyecto: "
                f"{getattr(project, 'goal', '') or getattr(project, 'name', '')}"
            )

    # Claves de conveniencia: no hacen daño si nadie las lee, y permiten specs
    # nuevos más naturales.
    seed["task_request"] = request  # siempre la petición actual
    seed.setdefault("project_context", _project_context(project))
    if _project_needs_workspace(project):
        seed.setdefault("workspace_root", str(PARADAX_ROOT))
        seed.setdefault("workspace_map", _workspace_map())
    return seed


def _required_seed_keys(project: Any) -> set[str]:
    pairs = [(aid, DYNAMIC.get(aid)) for aid in getattr(project, "agents", [])]
    agents = [a for _aid, a in pairs if a is not None]
    producers = {a.contract.writes for a in agents}
    required: set[str] = set()
    for agent in agents:
        for key in agent.contract.reads:
            if key != "model" and key not in producers:
                required.add(key)
    return required


def _project_context(project: Any) -> str:
    return (
        f"Proyecto: {getattr(project, 'name', '')}\n"
        f"Objetivo: {getattr(project, 'goal', '')}\n"
        f"Descripcion: {getattr(project, 'description', '')}"
    ).strip()


def _project_needs_workspace(project: Any) -> bool:
    return any(key in _WORKSPACE_KEYS | _WORKSPACE_MAP_KEYS for key in _required_seed_keys(project))


def _workspace_map(max_files: int = 120) -> str:
    """Mapa factual y compacto del repo para evitar que los agentes inventen rutas.

    Este mapa no reemplaza a las tools: obliga al modelo a partir de archivos
    reales antes de decidir un cambio.
    """
    root = PARADAX_ROOT.resolve()
    local_app = root / "local-agent-os"
    static_dir = local_app / "static"
    src_dir = local_app / "src"
    facts = [
        f"workspace_root: {root}",
        f"paradax_app_root: {local_app.relative_to(root) if local_app.exists() else 'NO_ENCONTRADO'}",
        f"frontend_static_dir: {static_dir.relative_to(root) if static_dir.exists() else 'NO_ENCONTRADO'}",
        f"src_dir_exists: {'si' if src_dir.exists() else 'no'}",
    ]
    if static_dir.exists():
        facts.append(
            "frontend_files: "
            + ", ".join(
                str((static_dir / name).relative_to(root))
                for name in ("index.html", "app.js", "styles.css")
                if (static_dir / name).exists()
            )
        )
    facts.append("regla: no asumas rutas src/ o componentes React si src_dir_exists=no.")

    files: list[str] = []
    priority_suffixes = (
        ".py", ".js", ".css", ".html", ".json", ".md", ".skw",
    )
    excluded = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache"}
    for path in sorted(root.rglob("*")):
        if len(files) >= max_files:
            break
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in excluded for part in rel.parts):
            continue
        if not str(rel).endswith(priority_suffixes):
            continue
        files.append(str(rel))
    return "\n".join([*facts, "archivos_relevantes:", *[f"- {file}" for file in files]])


def compute_plan(project: Any, seed_keys: set[str]) -> dict[str, Any]:
    """Arma el pipeline desde los CONTRATOS de los agentes (reads/writes):
    un agente corre cuando todas sus 'reads' están disponibles (semilla del
    proyecto o producidas por otro agente que corre antes). Resuelve el orden
    por dependencias de datos. NO ejecuta nada — sirve para previsualizar el
    pipeline y para que _contract_run sepa el orden. Devuelve orden, pasos
    (con qué falta) y edges de flujo de datos para el diagrama."""
    pairs = [(aid, DYNAMIC.get(aid)) for aid in project.agents]
    pairs = [(aid, a) for aid, a in pairs if a is not None]
    producers: dict[str, str] = {}
    for aid, a in pairs:
        producers[a.contract.writes] = aid

    available = set(seed_keys)
    order: list[str] = []
    pending = dict(pairs)
    progressed = True
    while pending and progressed:
        progressed = False
        for aid, a in list(pending.items()):
            reads = [r for r in a.contract.reads if r != "model"]
            if all(r in available for r in reads):
                order.append(aid)
                available.add(a.contract.writes)
                del pending[aid]
                progressed = True

    steps = []
    for aid, a in pairs:
        reads = [r for r in a.contract.reads if r != "model"]
        missing = [r for r in reads if r not in seed_keys and r not in producers]
        tier = effective_tier(a.spec) if getattr(a, "spec", None) else "tertiary"
        steps.append({
            "agent": aid, "name": a.contract.name,
            "reads": reads, "writes": a.contract.writes,
            "status": "scheduled" if aid in order else "blocked",
            "missing": missing, "tier": tier,
        })

    edges = []
    for aid, a in pairs:
        for r in a.contract.reads:
            if r in producers and producers[r] != aid:
                edges.append({"from": producers[r], "to": aid, "label": r})

    return {"order": order, "steps": steps, "edges": edges,
            "blocked": [aid for aid, _ in pairs if aid not in order]}


async def _contract_run(
    project: Any,
    model: str,
    run_id: str,
    seed_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Ejecuta el proyecto siguiendo el plan por contratos: siembra el contexto
    con project.inputs y corre cada agente en orden de dependencias, hilando las
    salidas de unos como entradas de otros. Los bloqueados (les falta una clave
    que nadie produce ni está en la semilla) se reportan, no rompen el run."""
    seed = dict(seed_override if seed_override is not None else (getattr(project, "inputs", {}) or {}))
    plan = compute_plan(project, set(seed.keys()))
    pipe = Pipeline(run_id)
    pipe.ctx.update(seed)
    # El modelo elegido para el run DEBE llegar a los agentes: ellos leen
    # ctx["model"] (si falta, caen al DEFAULT_MODEL e ignoran la elección).
    pipe.ctx["model"] = model
    ran: list[str] = []
    errors: list[dict[str, str]] = []
    skipped: list[dict[str, Any]] = []
    outputs: dict[str, Any] = {}
    for aid in plan["order"]:
        agent = DYNAMIC.get(aid)
        if agent is None:
            continue
        reads = [r for r in agent.contract.reads if r != "model"]
        missing_now = [r for r in reads if r not in pipe.ctx]
        if missing_now:
            skipped.append({"agent": aid, "missing": missing_now})
            db.add_event(run_id, "agent_skipped", {"agent": aid, "missing": missing_now})
            BUS.publish("agent_skipped", {"run_id": run_id, "agent": aid, "missing": missing_now})
            continue
        try:
            # El ejecutor local corre read-only (no escribe); así no rompe nada y
            # va a 'blocked' de forma determinista → Claude Code hace la escritura.
            _orig_rt = getattr(agent, "runtime", None)
            if _is_executor(agent) and _orig_rt is not None:
                agent.runtime = _READ_ONLY_RUNTIME
            try:
                await pipe.step(agent)
            finally:
                if _orig_rt is not None:
                    agent.runtime = _orig_rt
            ran.append(aid)
            out = pipe.ctx.get(agent.contract.writes)
            # HÍBRIDO: el local intentó y no logró cambiar nada → Claude Code ejecuta.
            if ENABLE_CLAUDE_ESCALATION and _is_executor(agent) and _is_blocked(out):
                task_text = pipe.ctx.get("feature_request") or pipe.ctx.get("task_request") or ""
                BUS.publish("agent_escalated", {"run_id": run_id, "agent": aid, "to": "claude_code"})
                db.add_event(run_id, "agent_escalated", {"agent": aid, "to": "claude_code"})
                # Solo la petición LITERAL: el technical_spec del modelo local puede
                # estar alucinado y envenenar a Claude Code. La petición manda.
                esc = await _escalate_executor(task_text, None)
                merged = dict(out) if isinstance(out, dict) else {}
                merged.update({
                    "summary": esc.get("summary", ""),
                    "changed_files": esc.get("changed_files", []),
                    "status": esc.get("status", "blocked"),
                    "tests_run": esc.get("tests_run", merged.get("tests_run", [])),
                    "escalated_to": "claude_code",
                })
                pipe.ctx[agent.contract.writes] = merged
                out = merged
                BUS.publish("agent_completed", {
                    "run_id": run_id, "agent": aid, "writes": agent.contract.writes,
                    "summary": f"Claude Code: {len(esc.get('changed_files', []))} archivo(s) cambiados",
                })
            outputs[aid] = out
        except Exception as exc:
            err = str(exc)[:500]
            errors.append({"agent": aid, "error": err})
            db.add_event(run_id, "agent_failed", {"agent": aid, "error": err})
    return {
        "ran": ran,
        "blocked": plan["blocked"],
        "errors": errors,
        "skipped": skipped,
        "outputs": outputs,
        "plan": plan["steps"],
        "note": "orquestación por contratos (reads/writes)",
    }


_WRITE_TOOLS = {"code_replace", "code_write_file"}
ENABLE_CLAUDE_ESCALATION = True
# El ejecutor local corre SIN tools de escritura: planifica/analiza pero no puede
# romper el código. La escritura real la hace Claude Code en el escalado.
_READ_ONLY_RUNTIME = DEFAULT_RUNTIME.without(_WRITE_TOOLS)


def _is_executor(agent: Any) -> bool:
    """Un agente que DEBE cambiar el código real (tiene tools de escritura)."""
    return bool(_WRITE_TOOLS & set(getattr(agent.contract, "allowed_tools", ())))


def _is_blocked(out: Any) -> bool:
    if not isinstance(out, dict):
        return False
    status = str(out.get("status", "")).lower()
    if status in {"blocked", "bloqueado", "failed", "error"}:
        return True
    if "changed_files" in out and not (out.get("changed_files") or []):
        return True
    return False


async def _escalate_executor(task: str, technical_spec: Any) -> dict[str, Any]:
    """Hook de ejecución real (Claude Code). Separado para poder testearlo."""
    from .factory import code_executor
    return await code_executor.claude_execute(task, PARADAX_ROOT, technical_spec=technical_spec)


def result_status(result: dict[str, Any]) -> str:
    """Estado honesto del run/tarea según los outputs reales."""
    if result.get("errors"):
        return "failed"
    if result.get("skipped"):
        return "blocked"
    if not result.get("ran") and result.get("blocked"):
        return "blocked"

    outputs = result.get("outputs") or {}
    for payload in outputs.values():
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("status", "")).lower()
        if status in {"blocked", "bloqueado"}:
            return "blocked"
        if status in {"failed", "error", "failed_verification"}:
            return "failed"
    for payload in outputs.values():
        if isinstance(payload, dict) and payload.get("ok") is False:
            return "failed"
    return "completed"


ENABLE_SAFETY = True
ENABLE_SANDBOX = True

# Palabras clave en el id/nombre del proyecto → task_kind para el ToolBroker.
_KIND_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("media", "reel", "gif", "video", "recorder"), "media"),
    (("jobsearch", "busqueda", "empleo", "trabajo"), "jobsearch"),
    (("code", "codigo", "feature", "refactor", "build"), "code"),
]


def _detect_task_kind(project: Any) -> str:
    text = f"{getattr(project, 'id', '')} {getattr(project, 'name', '')} {getattr(project, 'goal', '')}".lower()
    for hints, kind in _KIND_HINTS:
        if any(h in text for h in hints):
            return kind
    return "system"


def _build_agent_contracts(project: Any) -> dict[str, frozenset[str]]:
    """Construye mapa agent_id → frozenset[allowed_tools] para Sentinel-Watch."""
    result: dict[str, frozenset[str]] = {}
    for aid in getattr(project, "agents", []):
        agent = DYNAMIC.get(aid)
        if agent is None:
            continue
        tools = frozenset(getattr(agent.contract, "allowed_tools", ()))
        result[aid] = tools
    return result


def _safety_snapshot(message: str) -> str:
    """Punto de restauración git (resiliente: nunca rompe el run)."""
    if not ENABLE_SAFETY:
        return ""
    try:
        from .factory import safety
        safety.ensure_repo()
        return safety.snapshot(message)
    except Exception:
        return ""


async def run_project(
    project: Any,
    model: str = DEFAULT_MODEL,
    *,
    request: str | None = None,
    seed_override: dict[str, Any] | None = None,
    schedule_id: str = "",
    deadline_time: str = "",
) -> dict[str, Any]:
    """Ejecuta el pipeline del proyecto. Pensado para lanzarse en segundo plano."""
    import time as _time
    _start_ts = _time.monotonic()

    run_id = f"proj-{project.id[:24]}-{uuid.uuid4().hex[:6]}"
    db.init_db()
    run_request = request or project.goal or project.name
    db.create_run(run_id, f"project:{project.id}", run_request, model)
    BUS.publish("project_run_started", {
        "run_id": run_id,
        "project": project.id,
        "name": project.name,
        "request": request or "",
    })
    before_sha = _safety_snapshot(f"paradax: antes de {run_id}")
    watch_task: asyncio.Task | None = None
    monitor_task: asyncio.Task | None = None

    # Guardián del tiempo: si el run viene de un smart schedule con deadline,
    # vigila que termine antes de la hora límite y alerta si se pasa.
    if deadline_time:
        from .automation.monitor import AutomationMonitor
        monitor = AutomationMonitor(run_id, deadline_time, schedule_id)
        monitor_task = asyncio.create_task(monitor.watch(), name=f"automation-monitor-{run_id}")

    try:
        # Liberar la memoria de modelos residuales ANTES de la primera llamada:
        # sin esto, el modelo del run puede quedar en la cola de carga de ollama
        # detrás de un 30B con keep_alive vivo y morir por ReadTimeout.
        from . import ollama as _ollama
        await _ollama.ensure_only_model(model)

        runner = PROJECT_RUNNERS.get(project.id)
        seed = seed_override if seed_override is not None else task_inputs(project, run_request)

        if ENABLE_SANDBOX and runner is None:
            from .sandbox.bus import SandboxBus
            from .sandbox.sentinel_audit import SentinelAudit
            from .sandbox.sentinel_watch import SentinelWatch
            from .sandbox.tool_broker import ToolBroker

            task_kind = _detect_task_kind(project)
            broker = ToolBroker.for_task(run_id, task_kind)
            bus = SandboxBus()
            agent_contracts = _build_agent_contracts(project)
            watch = SentinelWatch(bus, broker, DEFAULT_RUNTIME, agent_contracts)
            watch_task = asyncio.create_task(watch.run(), name=f"sentinel-watch-{run_id}")

            # Inyectar bus y run_id en contextvars para ToolRuntime.call()
            SANDBOX_BUS_VAR.set(bus)
            SANDBOX_RUN_ID_VAR.set(run_id)

            db.add_event(run_id, "sandbox_started", {
                "task_kind": task_kind,
                "broker_tools": sorted(broker.allowed_tools),
            })
            BUS.publish("sandbox_started", {
                "run_id": run_id,
                "task_kind": task_kind,
                "broker_tools": sorted(broker.allowed_tools),
            })

        result = await runner(model) if runner else await _contract_run(project, model, run_id, seed)
        status = result_status(result)
        result = {"status": status, **result}

        # Audit post-run
        if ENABLE_SANDBOX and runner is None:
            await bus.close()
            if watch_task:
                try:
                    await asyncio.wait_for(watch_task, timeout=5.0)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    watch_task.cancel()
            audit = SentinelAudit().audit(run_id, before_sha)
            result["sandbox_audit"] = audit.model_dump()
            if audit.verdict == "rollback":
                status = "rollback"
                result["status"] = "rollback"

        # Snapshot de los cambios de los agentes → 'undo' al estado previo.
        after_sha = _safety_snapshot(f"paradax: run {run_id} — {run_request[:60]}")
        if before_sha:
            try:
                from .factory import safety
                result["undo"] = {"before_sha": before_sha, "after_sha": after_sha,
                                  "changed_files": safety.changed_files(before_sha)}
            except Exception:
                pass
        # El run terminó → el Guardián del tiempo ya no necesita vigilar.
        if monitor_task and not monitor_task.done():
            monitor_task.cancel()

        # Materializar el trabajo del run como ARCHIVOS visibles en
        # ~/paradax/resultados/<proyecto>/ — sin esto, todo queda en SQLite.
        try:
            from .artifacts import materialize_run
            run_row = db.get_run(run_id) or {}
            res_dir = materialize_run(
                project.id, project.name, run_id, run_request,
                run_row.get("events", []),
            )
            if res_dir:
                result["resultados"] = str(res_dir)
                db.add_event(run_id, "results_saved", {"dir": str(res_dir)})
                BUS.publish("results_saved", {"run_id": run_id, "project": project.id,
                                              "dir": str(res_dir)})
        except Exception:
            pass  # materializar nunca debe tumbar el run

        # Registrar duración para que el Team Automatización aprenda
        duration_s = _time.monotonic() - _start_ts
        try:
            from .automation.duration_tracker import DurationTracker
            DurationTracker().record(project.id, _detect_task_kind(project), duration_s)
            # Refinar el estimado del propio schedule que disparó este run.
            if schedule_id:
                from .automation.smart_scheduler import update_last_duration
                update_last_duration(schedule_id, duration_s)
        except Exception:
            pass

        db.finish_run(run_id, status, result)
        BUS.publish("project_run_finished",
                    {"run_id": run_id, "project": project.id, "status": status, "result": result,
                     "duration_seconds": round(duration_s, 1), "schedule_id": schedule_id})
        return {"run_id": run_id, **result}
    except Exception as exc:
        if watch_task and not watch_task.done():
            watch_task.cancel()
        if monitor_task and not monitor_task.done():
            monitor_task.cancel()
        db.add_event(run_id, "error", {"error": str(exc)})
        db.finish_run(run_id, "failed", error=str(exc))
        BUS.publish("project_run_finished",
                    {"run_id": run_id, "project": project.id, "status": "failed", "error": str(exc)[:300]})
        raise
