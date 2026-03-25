"""
Manage an indiserver process and its FIFO control channel.

Two modes:
  - Managed  (indi_manage_server=True, default): astrolol spawns indiserver
    with a FIFO, loads/unloads drivers dynamically via that FIFO.
  - Unmanaged (indi_manage_server=False): connect to an already-running
    indiserver at (indi_host, indi_port); driver loading is a no-op.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import structlog

logger = structlog.get_logger()

_FIFO_NAME = "astrolol_indi.fifo"
_STARTUP_WAIT = 2.0   # seconds to wait after spawning indiserver


class IndiServer:
    """
    Lifecycle manager for indiserver.

    Usage::

        server = IndiServer(manage=True, host="localhost", port=7624)
        await server.start()
        await server.load_driver("indi_asi_ccd")
        ...
        await server.stop()
    """

    def __init__(
        self,
        manage: bool = True,
        host: str = "localhost",
        port: int = 7624,
        fifo_dir: Path | None = None,
    ) -> None:
        self.manage = manage
        self.host = host
        self.port = port
        self._fifo_dir = fifo_dir or Path(tempfile.gettempdir())
        self._fifo_path = self._fifo_dir / _FIFO_NAME
        self._process: asyncio.subprocess.Process | None = None
        self._loaded_drivers: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self.manage:
            logger.info("indi.server_unmanaged", host=self.host, port=self.port)
            return

        if self._process is not None:
            return  # already running

        await self._create_fifo()

        cmd = [
            "indiserver",
            "-f", str(self._fifo_path),
            "-p", str(self.port),
            "-m", "100",   # max MB queued per client
        ]
        logger.info("indi.server_starting", cmd=" ".join(cmd))
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        # Give indiserver a moment to open the FIFO and start listening
        await asyncio.sleep(_STARTUP_WAIT)

        if self._process.returncode is not None:
            stderr = await self._process.stderr.read()  # type: ignore[union-attr]
            raise RuntimeError(
                f"indiserver exited immediately (rc={self._process.returncode}): "
                f"{stderr.decode().strip()}"
            )

        logger.info("indi.server_started", pid=self._process.pid, port=self.port)

    async def stop(self) -> None:
        if not self.manage or self._process is None:
            return

        logger.info("indi.server_stopping", pid=self._process.pid)
        self._process.terminate()
        try:
            await asyncio.wait_for(self._process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            self._process.kill()
            await self._process.wait()

        self._process = None
        self._loaded_drivers.clear()
        self._cleanup_fifo()
        logger.info("indi.server_stopped")

    async def load_driver(self, executable: str) -> None:
        """
        Tell indiserver to start a driver.

        In unmanaged mode this is a no-op — the remote server manages its
        own driver set.
        """
        if not self.manage:
            return

        if executable in self._loaded_drivers:
            logger.debug("indi.driver_already_loaded", driver=executable)
            return

        await self._fifo_write(f"start {executable}\n")
        self._loaded_drivers.add(executable)
        logger.info("indi.driver_loaded", driver=executable)

    async def unload_driver(self, executable: str) -> None:
        """Tell indiserver to stop a driver."""
        if not self.manage:
            return

        if executable not in self._loaded_drivers:
            return

        await self._fifo_write(f"stop {executable}\n")
        self._loaded_drivers.discard(executable)
        logger.info("indi.driver_unloaded", driver=executable)

    @property
    def is_running(self) -> bool:
        if not self.manage:
            return True  # assume remote server is up
        return self._process is not None and self._process.returncode is None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _create_fifo(self) -> None:
        self._fifo_dir.mkdir(parents=True, exist_ok=True)
        fifo = self._fifo_path
        if fifo.exists():
            fifo.unlink()
        await asyncio.to_thread(os.mkfifo, str(fifo))
        logger.debug("indi.fifo_created", path=str(fifo))

    async def _fifo_write(self, command: str) -> None:
        """Open the FIFO for writing (non-blocking so we don't hang)."""
        fifo = str(self._fifo_path)

        def _write() -> None:
            fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
            try:
                os.write(fd, command.encode())
            finally:
                os.close(fd)

        try:
            await asyncio.to_thread(_write)
        except OSError as exc:
            logger.warning("indi.fifo_write_failed", command=command.strip(), error=str(exc))

    def _cleanup_fifo(self) -> None:
        try:
            self._fifo_path.unlink(missing_ok=True)
        except OSError:
            pass
