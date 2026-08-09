"""Bounded offloading for synchronous model calls used by async routes."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any
from weakref import WeakKeyDictionary


def _bounded_int(value: str | None, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(parsed, high))


CLINICAL_IO_CONCURRENCY = _bounded_int(
    os.getenv("CLINICAL_IO_CONCURRENCY"),
    default=4,
    low=1,
    high=32,
)
CLINICAL_IO_TIMEOUT_SECONDS = _bounded_int(
    os.getenv("CLINICAL_IO_TIMEOUT_SECONDS"),
    default=45,
    low=5,
    high=180,
)


class ClinicalOperationTimeout(TimeoutError):
    """Raised without exposing provider details when a bounded call times out."""


_executor = ThreadPoolExecutor(
    max_workers=CLINICAL_IO_CONCURRENCY,
    thread_name_prefix="clinical-io",
)
_loop_limiters: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore] = (
    WeakKeyDictionary()
)


def _limiter(loop: asyncio.AbstractEventLoop) -> asyncio.Semaphore:
    limiter = _loop_limiters.get(loop)
    if limiter is None:
        limiter = asyncio.Semaphore(CLINICAL_IO_CONCURRENCY)
        _loop_limiters[loop] = limiter
    return limiter


async def run_clinical_io(
    operation: Callable[..., Any],
    /,
    *args: Any,
    timeout_seconds: float | None = None,
    **kwargs: Any,
) -> Any:
    """Run synchronous clinical/model work without blocking the event loop.

    Capacity is retained until the worker thread actually finishes, including
    after caller timeout or cancellation, so abandoned provider calls cannot
    bypass the concurrency bound.
    """

    loop = asyncio.get_running_loop()
    limiter = _limiter(loop)
    timeout = timeout_seconds or CLINICAL_IO_TIMEOUT_SECONDS
    future = None
    acquired = False
    deadline = loop.time() + timeout

    async def release_after_completion() -> None:
        while not future.done():
            await asyncio.sleep(0.01)
        limiter.release()

    try:
        await asyncio.wait_for(limiter.acquire(), timeout=timeout)
        acquired = True
        future = _executor.submit(partial(operation, *args, **kwargs))
        while not future.done():
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError
            await asyncio.sleep(min(0.01, remaining))
        return future.result()
    except TimeoutError as error:
        raise ClinicalOperationTimeout("clinical operation timed out") from error
    finally:
        if acquired:
            if future is None or future.done():
                limiter.release()
            elif not loop.is_closed():
                # Timeout/cancellation does not free capacity while the
                # provider thread is still running.
                loop.create_task(release_after_completion())
