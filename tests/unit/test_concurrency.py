"""Regression coverage for bounded FIFO capacity boundaries."""

from __future__ import annotations

import asyncio

import pytest

from academic_cluster.services.concurrency import (
    BoundedFifoGate,
    ConcurrencyQueueFullError,
    ConcurrencyQueueTimeoutError,
)


@pytest.mark.asyncio
async def test_gate_admits_waiters_in_fifo_order_and_rejects_overload() -> None:
    gate = BoundedFifoGate(capacity=1, max_waiters=1)
    await gate.acquire()
    acquired: list[str] = []

    async def wait_for_slot(name: str) -> None:
        async with gate.slot(timeout=1):
            acquired.append(name)

    first = asyncio.create_task(wait_for_slot("first"))
    await asyncio.sleep(0)

    with pytest.raises(ConcurrencyQueueFullError):
        await gate.acquire(timeout=0.01)

    await gate.release()
    await first
    assert acquired == ["first"]


@pytest.mark.asyncio
async def test_cancelled_or_timed_out_waiter_does_not_lose_a_gate_slot() -> None:
    gate = BoundedFifoGate(capacity=1, max_waiters=1)
    await gate.acquire()

    cancelled = asyncio.create_task(gate.acquire(timeout=1))
    await asyncio.sleep(0)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled

    with pytest.raises(ConcurrencyQueueTimeoutError):
        await gate.acquire(timeout=0.01)

    await gate.release()
    async with gate.slot(timeout=0.1):
        pass
