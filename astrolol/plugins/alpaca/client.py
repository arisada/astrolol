"""
ASCOM Alpaca client — the REST API Alpaca devices (and ASCOM Remote, OmniSim) serve.

Every device member is ``/api/v1/<type>/<number>/<member>``: GET reads a property, PUT sets
one or calls a method, with form parameters. Answers are JSON with ``Value``, ``ErrorNumber``
and ``ErrorMessage``; a non-zero ErrorNumber is the device's own error (0x400: not implemented).
Images come in Alpaca's binary ImageBytes format (asked for with an Accept header), not as the
JSON array, which is many times larger and slower to parse.

Alpaca has no push: adapters poll.
"""
from __future__ import annotations

import itertools
import random
import struct
from typing import Any

import httpx
import numpy as np
import structlog

logger = structlog.get_logger()

NOT_IMPLEMENTED = 0x400
INVALID_VALUE = 0x401
VALUE_NOT_SET = 0x402
NOT_CONNECTED = 0x407
INVALID_WHILE_PARKED = 0x408
INVALID_WHILE_SLAVED = 0x409
INVALID_OPERATION = 0x40B
ACTION_NOT_IMPLEMENTED = 0x40C

_DEFAULT_TIMEOUT = 10.0
_IMAGE_TIMEOUT = 120.0

# ImageBytes element types → numpy dtypes (little endian).
_ELEMENT_DTYPES = {
    1: "<i2",   # Int16
    2: "<i4",   # Int32
    3: "<f8",   # Double
    4: "<f4",   # Single
    5: "<u8",   # UInt64
    6: "u1",    # Byte
    7: "<i8",   # Int64
    8: "<u2",   # UInt16
    9: "<u4",   # UInt32
}
_IMAGEBYTES_HEADER = struct.Struct("<11i")


class AlpacaError(Exception):
    """An Alpaca device answered with an error, or could not be reached."""

    def __init__(self, message: str, number: int = 0) -> None:
        super().__init__(message)
        self.number = number


class AlpacaNotImplemented(AlpacaError):
    """The device does not implement this member (ErrorNumber 0x400)."""


def _form_value(value: Any) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    return str(value)


class AlpacaClient:
    """One Alpaca device: ``<base_url>/api/v1/<device_type>/<device_number>``."""

    # One client id per astrolol process; transaction ids count up per process.
    _client_id = random.randint(1, 2**31 - 1)
    _transactions = itertools.count(1)

    def __init__(
        self,
        host: str,
        port: int,
        device_type: str,
        device_number: int = 0,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.device_type = device_type.lower()
        self.device_number = int(device_number)
        self._timeout = timeout
        self._transport = transport
        self._http: httpx.AsyncClient | None = None

    @property
    def base_url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"

    @property
    def device_url(self) -> str:
        return f"{self.base_url}/api/v1/{self.device_type}/{self.device_number}"

    def __repr__(self) -> str:
        return f"AlpacaClient({self.device_url})"

    def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(timeout=self._timeout, transport=self._transport)
        return self._http

    def _ids(self) -> dict[str, str]:
        return {
            "ClientID": str(self._client_id),
            "ClientTransactionID": str(next(self._transactions)),
        }

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------

    async def get(self, member: str, **params: Any) -> Any:
        """Read a property (or a method that answers on GET, such as axisrates)."""
        query = {**self._ids(), **{k: _form_value(v) for k, v in params.items()}}
        try:
            response = await self._client().get(f"{self.device_url}/{member.lower()}", params=query)
        except httpx.HTTPError as exc:
            raise AlpacaError(f"{self.device_type} {self.device_number} unreachable at {self.base_url}: {exc}") from exc
        return self._value(member, response)

    async def put(self, member: str, timeout: float | None = None, **params: Any) -> Any:
        """Set a property or call a method. *params* use the Alpaca names (``Duration``, …)."""
        form = {**self._ids(), **{k: _form_value(v) for k, v in params.items()}}
        try:
            response = await self._client().put(
                f"{self.device_url}/{member.lower()}",
                data=form,
                timeout=timeout if timeout is not None else self._timeout,
            )
        except httpx.HTTPError as exc:
            raise AlpacaError(f"{self.device_type} {self.device_number} unreachable at {self.base_url}: {exc}") from exc
        return self._value(member, response)

    async def get_or(self, member: str, default: Any, **params: Any) -> Any:
        """A property the device may not implement: *default* when it does not."""
        try:
            return await self.get(member, **params)
        except AlpacaNotImplemented:
            return default

    def _value(self, member: str, response: httpx.Response) -> Any:
        if response.status_code != 200:
            # 400: bad parameter, 500: driver failure; the body is plain text.
            raise AlpacaError(
                f"{self.device_type} {member}: HTTP {response.status_code} {response.text.strip()[:200]}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise AlpacaError(f"{self.device_type} {member}: not an Alpaca answer") from exc
        number = int(body.get("ErrorNumber") or 0)
        if number:
            message = str(body.get("ErrorMessage") or f"error {number:#x}")
            cls = AlpacaNotImplemented if number in (NOT_IMPLEMENTED, ACTION_NOT_IMPLEMENTED) else AlpacaError
            raise cls(f"{self.device_type} {member}: {message}", number)
        return body.get("Value")

    # ------------------------------------------------------------------

    async def image_array(self) -> np.ndarray:
        """The last image, as rows × columns (× planes for a colour image).

        Alpaca sends it indexed [x][y] (x the slowest); FITS and numpy want rows first.
        """
        try:
            response = await self._client().get(
                f"{self.device_url}/imagearray",
                params=self._ids(),
                headers={"Accept": "application/imagebytes"},
                timeout=_IMAGE_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            raise AlpacaError(f"camera {self.device_number}: image download failed: {exc}") from exc
        if response.headers.get("content-type", "").startswith("application/imagebytes"):
            return parse_image_bytes(response.content)
        # A device without ImageBytes: the JSON array.
        value = self._value("imagearray", response)
        array = np.asarray(value)
        return np.ascontiguousarray(np.swapaxes(array, 0, 1))


def parse_image_bytes(data: bytes) -> np.ndarray:
    """Decode an Alpaca ImageBytes answer into rows × columns (× planes)."""
    if len(data) < _IMAGEBYTES_HEADER.size:
        raise AlpacaError("image: answer too short")
    (_version, error, _client_tx, _server_tx, data_start, _image_type, transmission_type,
     rank, dim1, dim2, dim3) = _IMAGEBYTES_HEADER.unpack_from(data)
    if error:
        message = data[data_start:].decode("utf-8", "replace") if data_start < len(data) else ""
        raise AlpacaError(f"image: {message or f'error {error:#x}'}", error)
    dtype = _ELEMENT_DTYPES.get(transmission_type)
    if dtype is None:
        raise AlpacaError(f"image: unknown element type {transmission_type}")
    shape = (dim1, dim2) if rank == 2 else (dim1, dim2, dim3)
    pixels = np.frombuffer(data, dtype=dtype, offset=data_start)
    expected = int(np.prod(shape))
    if pixels.size != expected:
        raise AlpacaError(f"image: {pixels.size} values for a {'×'.join(map(str, shape))} image")
    return np.ascontiguousarray(np.swapaxes(pixels.reshape(shape), 0, 1))
