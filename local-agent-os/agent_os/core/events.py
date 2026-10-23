from __future__ import annotations

"""Bus de eventos en memoria para la actividad en vivo (SSE).

Diseño orientado a NO impactar RAM ni procesos:
- `history`: deque ACOTADO (maxlen) — los clientes nuevos reciben el contexto
  reciente sin guardar nada en disco ni crecer sin límite.
- Cada suscriptor tiene una cola ACOTADA. Si un cliente lento se atasca, se
  descarta el evento más viejo (drop-oldest) en vez de acumular memoria.
- No persiste nada: el pipeline ya guarda en SQLite; esto solo "tea" los
  eventos a quien esté mirando en vivo.

El pipeline corre en el mismo loop asyncio que el servidor, así que `publish`
es seguro on-loop. Para llamadas desde otro hilo se usa call_soon_threadsafe.
"""

import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

HISTORY_SIZE = 200
QUEUE_SIZE = 100


class EventBus:
    def __init__(self, history_size: int = HISTORY_SIZE):
        self._subscribers: set[asyncio.Queue] = set()
        self._history: deque[dict[str, Any]] = deque(maxlen=history_size)
        self._seq = 0

    def publish(self, kind: str, data: dict[str, Any] | None = None) -> None:
        self._seq += 1
        event = {"seq": self._seq, "ts": round(time.time(), 3), "kind": kind, **(data or {})}
        self._history.append(event)
        for q in list(self._subscribers):
            _offer(q, event)

    async def subscribe(self, replay: bool = True) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._subscribers.add(q)
        try:
            if replay:
                for event in list(self._history):
                    _offer(q, event)
            while True:
                yield await q.get()
        finally:
            self._subscribers.discard(q)

    def snapshot(self, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._history)[-limit:]

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


def _offer(q: asyncio.Queue, event: dict[str, Any]) -> None:
    """Encola sin bloquear; si está llena, descarta el más viejo (acota RAM)."""
    try:
        q.put_nowait(event)
    except asyncio.QueueFull:
        try:
            q.get_nowait()
            q.put_nowait(event)
        except (asyncio.QueueEmpty, asyncio.QueueFull):
            pass


# Singleton del proceso.
BUS = EventBus()
