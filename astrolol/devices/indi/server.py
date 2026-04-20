"""
Manage an indiserver process and its FIFO control channel.

Two modes:
  - Managed  (indi_manage_server=True, default): astrolol spawns indiserver
    with a FIFO, loads/unloads drivers dynamically via that FIFO.
    The indiserver process survives astrolol restarts — state is persisted
    to <run_dir>/astrolol_indi.json so the next instance can reuse it.
  - Unmanaged (indi_manage_server=False): connect to an already-running
    indiserver at (indi_host, indi_port); driver loading is a no-op.
"""
from __future__ import annotations

import asyncio
import errno
import json
import os
import signal
import socket
from pathlib import Path

import structlog

logger = structlog.get_logger()

_FIFO_NAME = "astrolol_indi.fifo"
_STATE_NAME = "astrolol_indi.json"
_STARTUP_WAIT = 2.0   # seconds to wait after spawning indiserver


class IndiServer:
    """
    Lifecycle manager for indiserver.

    The indiserver process is detached from astrolol's process group
    (start_new_session=True) so it survives astrolol restarts.  State
    (PID and loaded drivers) is persisted to <run_dir>/astrolol_indi.json
    and restored on the next startup.

    Usage::

        server = IndiServer(manage=True, host="localhost", port=7624)
        await server.start()
        await server.load_driver("indi_asi_ccd")
        ...
        await server.stop()  # explicit — not called on normal astrolol exit
    """

    def __init__(
        self,
        manage: bool = True,
        host: str = "localhost",
        port: int = 7624,
        run_dir: Path = Path("/tmp/astrolol"),
    ) -> None:
        self.manage = manage
        self.host = host
        self.port = port
        self._run_dir = run_dir
        self._fifo_path = run_dir / _FIFO_NAME
        self._state_path = run_dir / _STATE_NAME
        self._managed_pid: int | None = None
        self._loaded_drivers: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if not self.manage:
            logger.info("indi.server_unmanaged", host=self.host, port=self.port)
            return

        if self._managed_pid is not None:
            return  # already managing in this instance

        # Check for a surviving indiserver from a previous astrolol run
        state = self._read_state()
        if state:
            pid = state.get("pid")
            if pid and self._is_our_indiserver(pid):
                logger.info("indi.server_reusing", pid=pid)
                self._managed_pid = pid
                self._loaded_drivers = set(state.get("loaded_drivers", []))
                return
            else:
                # Stale state — clean up
                logger.info("indi.server_stale_state", old_pid=pid)
                self._cleanup_state()

        # Check if something else is occupying the port
        if self._port_in_use(self.port):
            raise RuntimeError(
                f"Port {self.port} is in use by an unknown process. "
                "Stop it before starting astrolol, or switch to unmanaged mode."
            )

        # Spawn a fresh indiserver in its own session (detached from astrolol)
        self._run_dir.mkdir(parents=True, exist_ok=True)
        await self._create_fifo()

        cmd = [
            "indiserver",
            "-f", str(self._fifo_path),
            "-p", str(self.port),
            "-m", "100",   # max MB queued per client
        ]
        logger.info("indi.server_starting", cmd=" ".join(cmd))
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        # Give indiserver a moment to open the FIFO and start listening
        await asyncio.sleep(_STARTUP_WAIT)

        if process.returncode is not None:
            raise RuntimeError(
                f"indiserver exited immediately (rc={process.returncode})"
            )

        self._managed_pid = process.pid
        self._loaded_drivers = set()
        self._save_state()
        logger.info("indi.server_started", pid=process.pid, port=self.port)

    async def stop(self) -> None:
        """Explicitly stop the indiserver.

        Reads the PID from the state file, sends SIGTERM, waits, then SIGKILL.
        Only call this when the user explicitly wants to stop indiserver — NOT
        on normal astrolol shutdown.
        """
        if not self.manage:
            return

        state = self._read_state()
        pid = (state or {}).get("pid") or self._managed_pid
        if pid is None:
            logger.info("indi.server_not_running")
            return

        logger.info("indi.server_stopping", pid=pid)
        try:
            os.kill(pid, signal.SIGTERM)
            # Wait up to 5 s for graceful exit
            for _ in range(50):
                await asyncio.sleep(0.1)
                try:
                    os.kill(pid, 0)  # probe: raises ProcessLookupError if dead
                except ProcessLookupError:
                    break
            else:
                # Force kill if still alive after 5 s
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        except ProcessLookupError:
            pass  # already dead

        self._managed_pid = None
        self._loaded_drivers.clear()
        self._cleanup_state()
        self._cleanup_fifo()
        logger.info("indi.server_stopped", pid=pid)

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
        self._save_state()
        logger.info("indi.driver_loaded", driver=executable)

    async def unload_driver(self, executable: str) -> None:
        """Tell indiserver to stop a driver."""
        if not self.manage:
            return

        if executable not in self._loaded_drivers:
            return

        await self._fifo_write(f"stop {executable}\n")
        self._loaded_drivers.discard(executable)
        self._save_state()
        logger.info("indi.driver_unloaded", driver=executable)

    @property
    def is_running(self) -> bool:
        if not self.manage:
            return True  # assume remote server is up
        if self._managed_pid is not None:
            return self._is_our_indiserver(self._managed_pid)
        # Check state file (surviving from a previous instance)
        state = self._read_state()
        if state:
            pid = state.get("pid")
            return bool(pid and self._is_our_indiserver(pid))
        return False

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_our_indiserver(pid: int) -> bool:
        """Return True if pid is a running indiserver process."""
        try:
            comm_path = Path(f"/proc/{pid}/comm")
            if not comm_path.exists():
                return False
            return comm_path.read_text().strip() == "indiserver"
        except OSError:
            return False

    @staticmethod
    def _port_in_use(port: int) -> bool:
        """Return True if something is listening on localhost:port."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", port)) == 0

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def _read_state(self) -> dict | None:
        try:
            return json.loads(self._state_path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def _save_state(self) -> None:
        try:
            self._run_dir.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps({
                    "pid": self._managed_pid,
                    "loaded_drivers": sorted(self._loaded_drivers),
                })
            )
        except OSError as exc:
            logger.warning("indi.state_save_failed", error=str(exc))

    def _cleanup_state(self) -> None:
        try:
            self._state_path.unlink(missing_ok=True)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _create_fifo(self) -> None:
        fifo = self._fifo_path
        # Remove stale FIFO if present — indiserver hasn't opened it yet
        if fifo.exists():
            fifo.unlink()
        await asyncio.to_thread(os.mkfifo, str(fifo))
        logger.debug("indi.fifo_created", path=str(fifo))

    async def _fifo_write(self, command: str) -> None:
        """Open the FIFO for writing and send command.

        Uses O_NONBLOCK so we never block forever, but retries on ENXIO
        (no reader yet — indiserver hasn't opened the FIFO for reading).
        Retries for up to 5 seconds with short back-off.
        """
        fifo = str(self._fifo_path)

        def _write() -> None:
            fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
            try:
                os.write(fd, command.encode())
            finally:
                os.close(fd)

        deadline = asyncio.get_event_loop().time() + 5.0
        delay = 0.2
        while True:
            try:
                await asyncio.to_thread(_write)
                return
            except OSError as exc:
                if exc.errno == errno.ENXIO and asyncio.get_event_loop().time() < deadline:
                    # indiserver hasn't opened the FIFO for reading yet — wait and retry
                    logger.debug("indi.fifo_not_ready", command=command.strip(), retry_in=delay)
                    await asyncio.sleep(delay)
                    delay = min(delay * 1.5, 1.0)
                else:
                    logger.warning("indi.fifo_write_failed", command=command.strip(), error=str(exc))
                    return

    def _cleanup_fifo(self) -> None:
        try:
            self._fifo_path.unlink(missing_ok=True)
        except OSError:
            pass
