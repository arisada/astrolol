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


class BluetoothLinkClosedError(BluetoothTransportError):
    """The RFCOMM socket was closed out from under us (BT link dropped)."""


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
        """Send a command and return its terminated response.

        A clearly-closed link (``BluetoothLinkClosedError`` -- the socket was
        dropped, not just slow to answer) is treated as transient: the next
        call transparently reopens the RFCOMM socket and retries once, so a
        caller doing nothing more than periodic ``ping()``s self-heals after a
        Bluetooth drop without ever seeing an error, the same way a USB-serial
        adapter coming back on the same device node would. A plain timeout is
        NOT treated this way -- the link may still be live with a command in
        flight, and reconnecting underneath it risks the peripheral seeing the
        same command twice.
        """
        if self._sock is None or self._lock is None:
            raise BluetoothTransportError("Transport is not open")
        async with self._lock:
            try:
                response = await self._run(lambda: self._exchange(command))
            except BluetoothLinkClosedError:
                logger.warning("bluetooth.rfcomm_reconnecting", device_id=self._device_id)
                await self._reopen()
                response = await self._run(lambda: self._exchange(command))
                logger.info("bluetooth.rfcomm_reconnected", device_id=self._device_id)
        logger.debug("bluetooth.rfcomm_exchange", command=command, response=response)
        return response

    async def _reopen(self) -> None:
        if self._sock is not None:
            old_sock = self._sock
            self._sock = None
            await self._run(old_sock.close)
        try:
            sock = await self._manager.open(self._device_id)
            sock.settimeout(self._timeout)
        except Exception as exc:
            raise BluetoothTransportError(
                f"Could not reopen the Bluetooth link to '{self._device_id}': {exc}"
            ) from exc
        self._sock = sock

    def _exchange(self, command: bytes) -> bytes:
        assert self._sock is not None
        try:
            self._sock.sendall(command)
            buf = b""
            while not buf.endswith(self._terminator):
                chunk = self._sock.recv(256)
                if not chunk:
                    raise BluetoothLinkClosedError(f"Bluetooth link to '{self._device_id}' closed")
                buf += chunk
        except socket.timeout as exc:
            raise BluetoothTimeoutError(
                f"No response to {command!r} from device '{self._device_id}'"
            ) from exc
        except OSError as exc:
            raise BluetoothLinkClosedError(f"Bluetooth link to '{self._device_id}' closed: {exc}") from exc
        return buf

    async def _run(self, fn):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, fn)
