from __future__ import annotations

"""Sentinel-Audit: Daemon 2 — auditor post-run.

Se invoca al terminar cada run (desde project_runner.py). Lee la traza de
eventos SQLite del run, analiza las tool calls que pasaron por el sandbox,
y genera un AuditReport.

Si el número de tool calls bloqueadas supera VIOLATION_THRESHOLD, hace
rollback del árbol de trabajo via safety.undo_to(pre_sha). Esto deshace
cualquier cambio de filesystem que los agentes hayan causado durante el run.

No corre como loop — es una llamada síncrona de auditoría, no un daemon.
El nombre "Daemon 2" es conceptual: es el segundo guardián, pero actúa
puntualmente al final de cada run.
"""

import logging

from .. import db
from ..factory.safety import undo_to
from .protocol import AuditReport

logger = logging.getLogger(__name__)

# Si hay más de N tool calls bloqueadas en un run → rollback automático.
# Configurable por variable de entorno si se necesita afinar.
VIOLATION_THRESHOLD = 3


class SentinelAudit:
    def __init__(self, threshold: int = VIOLATION_THRESHOLD) -> None:
        self.threshold = threshold

    def audit(self, run_id: str, pre_sha: str = "") -> AuditReport:
        """Audita el run y devuelve el reporte. Hace rollback si procede."""
        run = db.get_run(run_id)
        if run is None:
            logger.warning("Audit: run_id no encontrado en DB: %s", run_id)
            return AuditReport(run_id=run_id, verdict="unknown")

        events = run.get("events", [])
        sandbox_events = [e for e in events if e["kind"] == "sandbox_tool"]

        total_tool_calls = len(sandbox_events)
        violations: list[str] = []

        for ev in sandbox_events:
            payload = ev.get("payload", {})
            if not payload.get("ok"):
                blocked_by = payload.get("blocked_by") or "watch"
                tool = payload.get("tool") or "unknown"
                agent = payload.get("agent_id") or "unknown"
                msg = f"tool '{tool}' bloqueada por '{blocked_by}' (agente: {agent})"
                violations.append(msg)
                logger.warning("Audit violation [%s]: %s", run_id, msg)

        blocked_calls = len(violations)

        if violations and blocked_calls > self.threshold and pre_sha:
            logger.error(
                "Audit: %d violaciones superan el umbral (%d) — rollback a sha=%s",
                blocked_calls, self.threshold, pre_sha,
            )
            result = undo_to(pre_sha)
            verdict = "rollback"
            rollback_sha = pre_sha if result.get("ok") else ""
            if not result.get("ok"):
                logger.error("Audit: rollback falló: %s", result.get("error"))
        elif violations:
            verdict = "violations"
            rollback_sha = ""
            logger.warning(
                "Audit: %d violaciones pero bajo umbral — run marcado con violations",
                blocked_calls,
            )
        else:
            verdict = "clean"
            rollback_sha = ""

        report = AuditReport(
            run_id=run_id,
            verdict=verdict,
            violations=violations,
            tool_calls=total_tool_calls,
            blocked_calls=blocked_calls,
            rollback_sha=rollback_sha,
        )

        db.add_event(run_id, "audit_report", report.model_dump())
        logger.info(
            "Audit completado | run=%s verdict=%s tool_calls=%d blocked=%d",
            run_id, verdict, total_tool_calls, blocked_calls,
        )
        return report
