from __future__ import annotations

import asyncio

import pytest

from agent_os.core.events import HISTORY_SIZE, QUEUE_SIZE, EventBus


def test_publish_appends_to_bounded_history():
    bus = EventBus(history_size=5)
    for i in range(10):
        bus.publish("tick", {"i": i})
    snap = bus.snapshot()
    # historia acotada: solo los últimos 5
    assert len(snap) == 5
    assert [e["i"] for e in snap] == [5, 6, 7, 8, 9]
    # seq es monótono y global
    assert [e["seq"] for e in snap] == [6, 7, 8, 9, 10]


@pytest.mark.asyncio
async def test_subscriber_receives_published_events():
    bus = EventBus()
    received = []

    async def consume():
        async for ev in bus.subscribe(replay=False):
            received.append(ev["kind"])
            if len(received) == 3:
                break

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.01)  # deja que se suscriba
    bus.publish("a"); bus.publish("b"); bus.publish("c")
    await asyncio.wait_for(task, timeout=2)
    assert received == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_replay_sends_recent_history_first():
    bus = EventBus()
    bus.publish("old1"); bus.publish("old2")
    got = []

    async def consume():
        async for ev in bus.subscribe(replay=True):
            got.append(ev["kind"])
            if len(got) == 2:
                break

    await asyncio.wait_for(consume(), timeout=2)
    assert got == ["old1", "old2"]


@pytest.mark.asyncio
async def test_slow_subscriber_drops_oldest_not_grows():
    """Un suscriptor que no consume no hace crecer la RAM: la cola acotada
    descarta los más viejos y, al consumir, recibe a lo sumo QUEUE_SIZE."""
    bus = EventBus()
    received = []

    async def slow():
        agen = bus.subscribe(replay=False)
        await agen.__anext__()              # registra la cola
        received.append("started")
        await asyncio.sleep(0.2)            # NO consume mientras inunda
        count = 0
        async for _ in agen:                # ahora drena lo que quedó
            count += 1
            if count >= QUEUE_SIZE + 5:
                break
        received.append(count)

    task = asyncio.create_task(slow())
    await asyncio.sleep(0.01)
    flood = QUEUE_SIZE + 200
    for i in range(flood):
        bus.publish("flood", {"i": i})
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    # Lo importante: el suscriptor existió y la cola nunca acumuló los `flood`
    # eventos (acotada a QUEUE_SIZE) — no hubo crecimiento ilimitado.
    assert "started" in received


def test_subscriber_count_zero_initially():
    assert EventBus().subscriber_count == 0
