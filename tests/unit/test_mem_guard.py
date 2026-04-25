"""Unit tests for astrolol.core.mem_guard."""
import asyncio

import pytest

from astrolol.core import mem_guard as _mod
from astrolol.core.mem_guard import mem_guard


@pytest.fixture(autouse=True)
def _reset_guard():
    """Restore the module-level state after each test."""
    original = _mod._check_fn
    yield
    _mod._check_fn = original


async def test_guard_disabled_by_default():
    """Without configure(), the guard is off — context completes immediately."""
    entered = False
    async with mem_guard():
        entered = True
    assert entered


async def test_guard_disabled_allows_concurrent():
    """When disabled, two concurrent blocks run in parallel."""
    _mod.configure(lambda: False)
    order: list[str] = []

    async def task(name: str) -> None:
        async with mem_guard():
            order.append(f"{name}_enter")
            await asyncio.sleep(0)
            order.append(f"{name}_exit")

    await asyncio.gather(task("a"), task("b"))
    # Both entered before either exited (interleaved at the yield point)
    assert order.index("a_enter") < order.index("b_enter") or \
           order.index("b_enter") < order.index("a_enter")
    assert set(order) == {"a_enter", "a_exit", "b_enter", "b_exit"}


async def test_guard_enabled_serialises():
    """When enabled, concurrent blocks execute one at a time."""
    _mod.configure(lambda: True)
    order: list[str] = []

    async def task(name: str) -> None:
        async with mem_guard():
            order.append(f"{name}_enter")
            await asyncio.sleep(0)
            order.append(f"{name}_exit")

    await asyncio.gather(task("a"), task("b"))
    # With Semaphore(1), "a" must fully exit before "b" enters
    a_exit = order.index("a_exit")
    b_enter = order.index("b_enter")
    assert a_exit < b_enter


async def test_guard_live_toggle():
    """The check function is evaluated at each acquisition — changes take effect immediately."""
    enabled = False
    _mod.configure(lambda: enabled)

    order: list[str] = []

    async def task(name: str) -> None:
        async with mem_guard():
            order.append(f"{name}_enter")
            await asyncio.sleep(0)
            order.append(f"{name}_exit")

    # Disabled: concurrent
    await asyncio.gather(task("a"), task("b"))
    assert len(order) == 4

    order.clear()
    enabled = True

    # Enabled: serialised
    await asyncio.gather(task("c"), task("d"))
    c_exit = order.index("c_exit")
    d_enter = order.index("d_enter")
    assert c_exit < d_enter


async def test_guard_releases_on_exception():
    """Semaphore is released even if the guarded block raises."""
    _mod.configure(lambda: True)

    with pytest.raises(RuntimeError):
        async with mem_guard():
            raise RuntimeError("boom")

    # Guard should be acquirable again immediately
    acquired = False
    async with mem_guard():
        acquired = True
    assert acquired
