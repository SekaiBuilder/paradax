from __future__ import annotations

"""AutomationMonitor: vigila que un run automatizado termine antes del deadline.

Se lanza como asyncio.Task cuando el smart scheduler dispara un run. Cada 60s
comprueba si el run terminó en DB. Si la hora actual supera el deadline y el
run sigue activo, publica `automation_at_risk` al BUS y marca el run en DB.

Se auto-cancela cuando detecta `project_run_finished` en el BUS o cuando el
run aparece como terminado en DB.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from .. import db
from ..core.events import BUS

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 60


class AutomationMonitor:
    def __init__(self, run_id: str, deadline_time: str, schedule_id: str = "") -> None:
        self.run_id = run_id
        self.deadline_time = deadline_time  # "HH:MM"
        self.schedule_id = schedule_id
        self._alerted = False

    async def watch(self) -> None:
        """Loop principal. Correr como asyncio.Task."""
        logger.info(
            "AutomationMonitor iniciado | run=%s deadline=%s",
            self.run_id, self.deadline_time,
        )
        while True:
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            try:
                finished = await self._check()
                if finished:
                    logger.info("AutomationMonitor: run %s terminó — deteniendo", self.run_id)
                    break
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("AutomationMonitor error: %s", exc)

    async def _check(self) -> bool:
        """Devuelve True si el run terminó (ok o con error). Emite alerta si procede."""
        run = db.get_run(self.run_id)
        if run is None:
            return False

        status = run.get("status", "running")
        if status in {"completed", "failed", "rollback", "blocked"}:
            return True

        # El run sigue activo — ¿superamos el deadline?
        now = datetime.now()
        try:
            h, m = map(int, self.deadline_time.split(":"))
            deadline_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
        except ValueError:
            return False

        if now > deadline_dt and not self._alerted:
            self._alerted = True
            payload: dict[str, Any] = {
                "run_id": self.run_id,
                "schedule_id": self.schedule_id,
                "deadline": self.deadline_time,
                "now": now.strftime("%H:%M"),
                "status": "at_risk",
            }
            BUS.publish("automation_at_risk", payload)
            db.add_event(self.run_id, "automation_at_risk", payload)
            logger.warning(
                "DEADLINE SUPERADO | run=%s deadline=%s now=%s",
                self.run_id, self.deadline_time, now.strftime("%H:%M"),
            )

        return False
