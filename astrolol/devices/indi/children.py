"""Stopping the INDI/INDIGO servers astrolol started, without leaving zombies.

A restart (POST /admin/restart) re-executes astrolol in the same process, so a server started
before it is still astrolol's child but has no asyncio handle any more: once it exits, its exit
status must be collected with waitpid() or it stays a zombie until astrolol ends. A zombie also
still answers kill(pid, 0), so that probe alone never sees it go.
"""
from __future__ import annotations

import asyncio
import os
import signal

import structlog

logger = structlog.get_logger()


def reap(pid: int) -> bool:
    """True if *pid* is a child of ours that has exited; its exit status is collected."""
    try:
        done, _ = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:   # not our child, or already collected
        return False
    return done == pid


def is_gone(pid: int) -> bool:
    """True once *pid* no longer runs (collected first if it was our child)."""
    if reap(pid):
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:     # someone else's process: it runs
        return False
    return False


async def terminate(pid: int, process: asyncio.subprocess.Process | None = None, timeout: float = 5.0) -> None:
    """SIGTERM *pid*, then SIGKILL if it is still there after *timeout* seconds.

    *process* is its asyncio handle when this run of astrolol started it: asyncio then
    collects the exit status. Without one, it is collected here.
    """
    if process is not None and process.pid == pid:
        if process.returncode is None:
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout)
            except ProcessLookupError:
                pass
            except TimeoutError:
                process.kill()
                await process.wait()
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        reap(pid)
        return
    if await _wait_gone(pid, timeout):
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await _wait_gone(pid, 1.0)


async def _wait_gone(pid: int, timeout: float) -> bool:
    for _ in range(max(1, int(timeout / 0.1))):
        if is_gone(pid):
            return True
        await asyncio.sleep(0.1)
    return is_gone(pid)


def reap_exited_children() -> None:
    """Collect children that exited before this run of astrolol could wait for them.

    Call at startup, before anything starts a subprocess: it collects any exited child.
    """
    while True:
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return
        logger.info("indi.left_over_child_collected", pid=pid, status=status)
