"""Unit tests for astrolol.core.mem_guard."""
import asyncio

import pytest

from astrolol.core import mem_guard as _mod
from astrolol.core.mem_guard import mem_guard


@pytest.fixture(autouse=True)
def _reset_guard():
    """Restore the module-level state after each test — including the lazily-bound
    semaphore/loop, so a test that rebinds it to a throwaway loop (see
    test_guard_rebinds_to_a_new_event_loop) doesn't leave this module's own shared
    loop-scoped tests pointed at a closed loop afterward."""
    original_check = _mod._check_fn
    original_sem, original_sem_loop = _mod._sem, _mod._sem_loop
    yield
    _mod._check_fn = original_check
    _mod._sem, _mod._sem_loop = original_sem, original_sem_loop


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


async def test_guard_rebinds_to_a_new_event_loop():
    """asyncio.Semaphore binds to whichever loop first awaits it. The app has exactly
    one loop for its whole process lifetime, so this never matters in production — but
    different test modules run on different loops (this repo scopes the test event loop
    per module), so a semaphore left bound to one module's loop would break every other
    module that exercises the enabled guard afterward, in the same pytest session."""
    _mod.configure(lambda: True)

    async with mem_guard():
        pass
    first_loop = _mod._sem_loop
    assert first_loop is asyncio.get_running_loop()

    # Simulate a different test module running on a separate loop. A thread (not
    # new_loop.run_until_complete here) since this coroutine's own loop is already
    # running and asyncio forbids nesting run_until_complete inside that.
    await asyncio.to_thread(asyncio.run, _use_guard_once())
    assert _mod._sem_loop is not first_loop


async def _use_guard_once() -> None:
    async with mem_guard():
        pass


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
