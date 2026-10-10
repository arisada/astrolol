"""Developer tools: update the checkout and rebuild the web UI."""
from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

from plugins.system.models import CommandResult

logger = structlog.get_logger()

REPO_ROOT = Path(__file__).resolve().parents[2]
UI_DIR = REPO_ROOT / "ui"
MAX_OUTPUT_CHARS = 20_000


async def _run(cmd: list[str], cwd: Path, timeout: float) -> CommandResult:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:
        return CommandResult(ok=False, output=f"Could not run {cmd[0]}: {exc}")
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return CommandResult(ok=False, output=f"Timed out after {timeout:.0f} s")
    except asyncio.CancelledError:
        proc.kill()
        raise
    text = out.decode(errors="replace").strip()
    if len(text) > MAX_OUTPUT_CHARS:
        text = "…" + text[-MAX_OUTPUT_CHARS:]
    logger.info("system.dev_command", cmd=cmd, returncode=proc.returncode)
    return CommandResult(ok=proc.returncode == 0, output=text)


async def git_pull() -> CommandResult:
    """Fast-forward the checkout; never merges or rewrites local work."""
    return await _run(["git", "pull", "--ff-only"], REPO_ROOT, timeout=120)


async def rebuild_ui() -> CommandResult:
    return await _run(["npm", "run", "build"], UI_DIR, timeout=900)
