"""Generic RFCOMM-socket transport for native (non-INDI) device drivers.

Mirrors the ``open()``/``close()``/``request(command) -> bytes`` shape of
``plugins/eqmod/transport.py``'s ``SerialTransport`` so a driver can treat a
paired Bluetooth device exactly like a serial port — pick a transport, not a
protocol. The socket is a plain AF_BLUETOOTH/BTPROTO_RFCOMM stream, opened via
``BluetoothManager.open()``; blocking socket calls run on a dedicated executor
thread, same reasoning as pyserial's blocking I/O in ``SerialTransport``.
"""
from __future__ import annotations

import asyncio
import socket
from concurrent.futures import ThreadPoolExecutor

import structlog

from astrolol.devices.bluetooth.manager import BluetoothManager

logger = structlog.get_logger()

DEFAULT_TIMEOUT = 2.0  # seconds


class BluetoothTransportError(RuntimeError):
    pass


class BluetoothTimeoutError(BluetoothTransportError):
    """No complete response before the timeout."""


class BluetoothRfcommTransport:
    def __init__(
        self,
        manager: BluetoothManager,
        device_id: str,
        terminator: bytes = b"\r",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._manager = manager
        self._device_id = device_id
        self._terminator = terminator
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._executor: ThreadPoolExecutor | None = None
        self._lock: asyncio.Lock | None = None

    async def open(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bt-rfcomm")
        self._lock = asyncio.Lock()
        sock = await self._manager.open(self._device_id)
        sock.settimeout(self._timeout)
        self._sock = sock

    async def close(self) -> None:
        if self._sock is not None:
            sock = self._sock
            self._sock = None
            await self._run(sock.close)
        if self._executor is not None:
            self._executor.shutdown(wait=False)
            self._executor = None

    async def request(self, command: bytes) -> bytes:
        if self._sock is None or self._lock is None:
            raise BluetoothTransportError("Transport is not open")
        async with self._lock:
            response = await self._run(lambda: self._exchange(command))
        logger.debug("bluetooth.rfcomm_exchange", command=command, response=response)
        return response

    def _exchange(self, command: bytes) -> bytes:
        assert self._sock is not None
        try:
            self._sock.sendall(command)
            buf = b""
            while not buf.endswith(self._terminator):
                chunk = self._sock.recv(256)
                if not chunk:
                    raise BluetoothTransportError(f"Bluetooth link to '{self._device_id}' closed")
                buf += chunk
        except socket.timeout as exc:
            raise BluetoothTimeoutError(
                f"No response to {command!r} from device '{self._device_id}'"
            ) from exc
        except OSError as exc:
            raise BluetoothTransportError(f"Bluetooth link to '{self._device_id}' closed: {exc}") from exc
        return buf

    async def _run(self, fn):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, fn)
