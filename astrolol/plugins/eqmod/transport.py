"""Serial transport for the Sky-Watcher motor controller.

pyserial is blocking, so every call runs on a dedicated single-thread executor;
the protocol is strictly one command -> one response, serialised by a lock.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import serial
import structlog

from astrolol.plugins.eqmod.protocol import EqmodProtocolError

logger = structlog.get_logger()

# EQMOD cable (TTL UART) runs at 9600; the AZ-EQ6's built-in USB port runs at 115200.
CANDIDATE_BAUDRATES = (115200, 9600)
DEFAULT_TIMEOUT = 1.0  # seconds


class EqmodTimeoutError(EqmodProtocolError):
    """No complete response before the timeout."""


class SerialTransport:
    def __init__(self, port: str, baudrate: int, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._serial: serial.Serial | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._lock: asyncio.Lock | None = None

    @property
    def baudrate(self) -> int:
        return self._baudrate

    async def open(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="eqmod-serial")
        self._lock = asyncio.Lock()
        self._serial = await self._run(
            lambda: serial.Serial(self._port, self._baudrate, timeout=self._timeout)
        )

    async def close(self) -> None:
        if self._serial is not None:
            ser = self._serial
            self._serial = None
            await self._run(ser.close)
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None

    async def request(self, command: bytes) -> bytes:
        if self._serial is None or self._lock is None:
            raise EqmodProtocolError("Transport is not open")
        async with self._lock:
            response = await self._run(lambda: self._exchange(command))
        logger.debug("eqmod.serial_exchange", command=command, response=response)
        return response

    def _exchange(self, command: bytes) -> bytes:
        assert self._serial is not None
        self._serial.reset_input_buffer()  # drop anything stale from a timed-out exchange
        self._serial.write(command)
        self._serial.flush()
        response = self._serial.read_until(b"\r")
        if not response.endswith(b"\r"):
            raise EqmodTimeoutError(
                f"No response to {command!r} on {self._port} at {self._baudrate} baud"
            )
        return response

    async def _run(self, fn):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, fn)


async def detect_baudrate(
    port: str,
    candidates: tuple[int, ...] = CANDIDATE_BAUDRATES,
    transport_factory: Callable[[str, int], SerialTransport] = SerialTransport,
) -> int:
    """Return the first baud rate at which the controller answers a version inquiry."""
    probe = b":e1\r"
    for baudrate in candidates:
        transport = transport_factory(port, baudrate)
        try:
            await transport.open()
            response = await transport.request(probe)
            if response.startswith(b"="):
                logger.info("eqmod.baudrate_detected", port=port, baudrate=baudrate)
                return baudrate
        except (EqmodProtocolError, serial.SerialException) as exc:
            logger.debug("eqmod.baudrate_probe_failed", port=port, baudrate=baudrate, error=str(exc))
        finally:
            await transport.close()
    raise EqmodProtocolError(f"No Sky-Watcher controller answered on {port} at {candidates}")
