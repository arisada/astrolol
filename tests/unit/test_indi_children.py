"""Stopping a server astrolol started leaves no zombie, with or without its asyncio handle."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

from astrolol.devices.indi.children import is_gone, reap, terminate


def _spawn(*argv: str) -> int:
    # No handle, like a server started before POST /admin/restart re-executed astrolol.
    return os.posix_spawnp(argv[0], list(argv), os.environ)


def _is_zombie(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].startswith("Z")
    except FileNotFoundError:
        return False


def _collected(pid: int) -> bool:
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        return True
    return False


async def test_a_child_without_handle_is_stopped_and_collected() -> None:
    pid = _spawn("sleep", "60")
    start = time.monotonic()
    await terminate(pid)
    assert time.monotonic() - start < 2      # not the 5 s a zombie used to cost
    assert _collected(pid) and not _is_zombie(pid)


async def test_a_child_that_ignores_sigterm_is_killed_and_collected() -> None:
    pid = _spawn("sh", "-c", "trap '' TERM; sleep 60")
    await asyncio.sleep(0.2)                  # the trap is set
    await terminate(pid, timeout=0.3)
    assert _collected(pid) and not _is_zombie(pid)


async def test_a_child_with_its_asyncio_handle() -> None:
    process = await asyncio.create_subprocess_exec("sleep", "60")
    await terminate(process.pid, process)
    assert process.returncode is not None


async def test_a_process_that_is_not_ours() -> None:
    # PID 1 runs and is not our child: nothing to collect, and it is not gone.
    assert reap(1) is False
    assert is_gone(1) is False


def test_children_left_over_by_the_previous_run_are_collected_at_startup() -> None:
    # In its own process: the startup sweep collects any exited child, which would take other
    # tests' subprocesses too.
    code = """
import os, time
from astrolol.devices.indi.children import reap_exited_children
pid = os.posix_spawnp("true", ["true"], os.environ)
time.sleep(0.3)
assert open(f"/proc/{pid}/stat").read().split(") ", 1)[1].startswith("Z")
reap_exited_children()
assert not os.path.exists(f"/proc/{pid}")
reap_exited_children()   # nothing left: returns
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=30)
