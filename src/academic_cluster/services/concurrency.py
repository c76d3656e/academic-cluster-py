"""Bounded FIFO concurrency primitives for external and Agent work.

``asyncio.Semaphore`` is intentionally small and fast, but it does not expose
queue admission, waiting deadlines, or a fairness contract.  The Agent API
needs all three so overload is rejected at a known boundary instead of
silently accumulating unbounded background tasks.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class ConcurrencyQueueFullError(RuntimeError):
    """Raised when a bounded work queue cannot accept another waiter."""


class ConcurrencyQueueTimeoutError(TimeoutError):
    """Raised when a waiter reaches its queueing deadline."""


class BoundedFifoGate:
    """A cancellation-safe, bounded FIFO gate.

    The gate has a fixed number of active slots and a fixed number of waiting
    slots.  A caller is admitted in arrival order, which prevents one noisy
    execution from repeatedly winning semaphore races against older work.
    """

    def __init__(self, *, capacity: int, max_waiters: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least one")
        if max_waiters < 0:
            raise ValueError("max_waiters cannot be negative")
        self._capacity = capacity
        self._max_waiters = max_waiters
        self._available = capacity
        self._waiters: deque[asyncio.Future[None]] = deque()
        self._lock = asyncio.Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def queued(self) -> int:
        """Return an approximate queue size for diagnostics and tests."""

        return sum(not waiter.done() for waiter in self._waiters)

    async def acquire(self, *, timeout: float | None = None) -> None:
        """Acquire one slot, rejecting overload and expiring stale waiters."""

        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[None] | None = None
        async with self._lock:
            if self._available and not self._waiters:
                self._available -= 1
                return
            if len(self._waiters) >= self._max_waiters:
                raise ConcurrencyQueueFullError("concurrency queue is full")
            waiter = loop.create_future()
            self._waiters.append(waiter)

        acquired = False
        must_release_after_error = False
        try:
            if timeout is None:
                await asyncio.shield(waiter)
            else:
                await asyncio.wait_for(asyncio.shield(waiter), timeout=timeout)
            acquired = True
        except TimeoutError as error:
            must_release_after_error = True
            raise ConcurrencyQueueTimeoutError(
                "concurrency queue wait deadline exceeded"
            ) from error
        except asyncio.CancelledError:
            must_release_after_error = True
            raise
        finally:
            if not acquired:
                async with self._lock:
                    if waiter.done() and not waiter.cancelled():
                        # A release may have handed the slot to this task just
                        # as it was cancelled or timed out. Return that slot.
                        acquired = True
                    else:
                        with contextlib.suppress(ValueError):
                            self._waiters.remove(waiter)
            if acquired and must_release_after_error:
                # A release may have handed the slot to this task just as its
                # wait timed out or was cancelled. Return that handoff.
                await self.release()

    async def release(self) -> None:
        """Release one slot to the oldest live waiter or to the pool."""

        async with self._lock:
            while self._waiters:
                waiter = self._waiters.popleft()
                if not waiter.done():
                    waiter.set_result(None)
                    return
            self._available = min(self._capacity, self._available + 1)

    @asynccontextmanager
    async def slot(self, *, timeout: float | None = None) -> AsyncIterator[None]:
        """Acquire and reliably release a single gate slot."""

        await self.acquire(timeout=timeout)
        try:
            yield
        finally:
            await self.release()
