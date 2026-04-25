"""Global memory-pressure semaphore.

When low-memory mode is enabled (``configure()`` wires up a live check), every
``async with mem_guard():`` block acquires a shared Semaphore(1), serialising
all registered memory-intensive work across the whole application — image
previews, plate-solve subprocesses, or any future heavy operation in plugins.

When low-memory mode is disabled the context manager is a no-op and imposes
no scheduling overhead.

Usage
-----
Wire up once at app startup::

    from astrolol.core import mem_guard
    mem_guard.configure(lambda: profile_store.get_user_settings().low_memory_mode)

Then wrap any memory-intensive operation::

    from astrolol.core.mem_guard import mem_guard

    async with mem_guard():
        await asyncio.to_thread(heavy_fn, ...)
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Callable

# Single global semaphore — limit of 1 means at most one guarded block runs at
# a time when low-memory mode is active.
_sem = asyncio.Semaphore(1)

# Replaced by configure(); returns False (guard disabled) until wired up.
_check_fn: Callable[[], bool] = lambda: False


def configure(check_fn: Callable[[], bool]) -> None:
    """Register the function that tests whether low-memory mode is active.

    Called once during app startup with a closure over the live UserSettings,
    so the check reflects the current setting without requiring a restart.
    """
    global _check_fn
    _check_fn = check_fn


@asynccontextmanager
async def mem_guard():
    """Async context manager that serialises work when low-memory mode is on.

    Acquires the global Semaphore(1) when ``_check_fn()`` returns True,
    effectively preventing concurrent execution of any guarded block.
    When disabled, yields immediately without touching the semaphore.
    """
    if _check_fn():
        async with _sem:
            yield
    else:
        yield
