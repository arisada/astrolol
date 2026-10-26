"""The Alpaca client and adapters without a device: a fake Alpaca server on httpx's MockTransport.

test_simulators.py runs the same adapters against OmniSim.
"""
from __future__ import annotations

import struct
from urllib.parse import parse_qs

import httpx
import numpy as np
import pytest

from astrolol.plugins.alpaca.client import (
    AlpacaClient,
    AlpacaError,
    AlpacaNotImplemented,
    parse_image_bytes,
)
from astrolol.plugins.alpaca.mount import AlpacaMount


def _image_bytes(pixels_xy: np.ndarray, transmission_type: int, *, error: int = 0, message: bytes = b"") -> bytes:
    """An ImageBytes answer for an array indexed [x][y], as Alpaca sends it."""
    dims = list(pixels_xy.shape) + [0] * (3 - pixels_xy.ndim)
    header = struct.pack("<11i", 1, error, 1, 1, 44, 2, transmission_type, pixels_xy.ndim, *dims)
    return header + (message if error else pixels_xy.tobytes())


def test_image_bytes_come_out_rows_first() -> None:
    xy = np.arange(12, dtype="<u2").reshape(4, 3)        # 4 columns (x), 3 rows (y)
    image = parse_image_bytes(_image_bytes(xy, 8))
    assert image.shape == (3, 4)
    assert image[1, 2] == xy[2, 1]                       # row y=1, column x=2


@pytest.mark.parametrize("transmission_type, dtype", [(6, "u1"), (1, "<i2"), (2, "<i4"), (4, "<f4")])
def test_image_bytes_element_types(transmission_type: int, dtype: str) -> None:
    xy = np.arange(6, dtype=dtype).reshape(2, 3)
    assert parse_image_bytes(_image_bytes(xy, transmission_type)).dtype == np.dtype(dtype)


def test_colour_image_keeps_its_planes() -> None:
    xyz = np.arange(24, dtype="<i4").reshape(4, 2, 3)
    assert parse_image_bytes(_image_bytes(xyz, 2)).shape == (2, 4, 3)


def test_image_bytes_errors() -> None:
    with pytest.raises(AlpacaError, match="no image"):
        parse_image_bytes(_image_bytes(np.zeros((1, 1)), 6, error=0x40B, message=b"no image"))
    with pytest.raises(AlpacaError, match="too short"):
        parse_image_bytes(b"\x01\x00")
    truncated = _image_bytes(np.zeros((4, 4), dtype="u1"), 6)[:-3]
    with pytest.raises(AlpacaError, match="values for a"):
        parse_image_bytes(truncated)


# ---------------------------------------------------------------------------
# A fake device
# ---------------------------------------------------------------------------

class FakeDevice:
    """Answers GETs from *values*, records PUTs; members in *missing* are not implemented."""

    def __init__(self, values: dict, missing: set[str] = frozenset()) -> None:
        self.values = dict(values)
        self.missing = set(missing)
        self.puts: list[tuple[str, dict]] = []
        self.client_ids: set[str] = set()
        self.transactions: list[int] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        member = request.url.path.rsplit("/", 1)[-1]
        if request.method == "PUT":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self._ids(form)
            self.puts.append((member, form))
            if member == "connected":
                self.values["connected"] = form["Connected"] == "True"
            return self._answer(None)
        self._ids(dict(request.url.params))
        if member == "bad":
            return httpx.Response(400, text="Bad parameter")
        if member in self.missing:
            return self._answer(0, 0x400, f"{member} is not implemented")
        if member == "canmoveaxis":
            return self._answer(self.values.get(f"canmoveaxis{request.url.params['Axis']}", True))
        return self._answer(self.values.get(member))

    def _ids(self, params: dict) -> None:
        self.client_ids.add(params["ClientID"])
        self.transactions.append(int(params["ClientTransactionID"]))

    @staticmethod
    def _answer(value: object, number: int = 0, message: str = "") -> httpx.Response:
        return httpx.Response(200, json={"Value": value, "ErrorNumber": number, "ErrorMessage": message,
                                         "ClientTransactionID": 1, "ServerTransactionID": 1})

    def client(self, device_type: str) -> AlpacaClient:
        return AlpacaClient("alpaca.local", 11111, device_type, 0, transport=httpx.MockTransport(self.handler))


async def test_values_errors_and_ids() -> None:
    device = FakeDevice({"name": "Scope"}, missing={"sideofpier"})
    client = device.client("telescope")
    assert client.device_url == "http://alpaca.local:11111/api/v1/telescope/0"
    assert await client.get("name") == "Scope"
    with pytest.raises(AlpacaNotImplemented):
        await client.get("sideofpier")
    assert await client.get_or("sideofpier", -1) == -1
    with pytest.raises(AlpacaError, match="HTTP 400 Bad parameter"):
        await client.get("bad")
    await client.put("tracking", Tracking=True, TrackingRate=2)
    assert device.puts[-1][1]["Tracking"] == "True"     # Alpaca's booleans
    assert device.puts[-1][1]["TrackingRate"] == "2"
    assert len(device.client_ids) == 1                  # one client id, transactions counting up
    assert device.transactions == sorted(device.transactions)
    await client.close()


async def test_unreachable_device() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)
    client = AlpacaClient("alpaca.local", 11111, "camera", 0, transport=httpx.MockTransport(refuse))
    with pytest.raises(AlpacaError, match="unreachable"):
        await client.get("connected")


def test_ipv6_host() -> None:
    assert AlpacaClient("::1", 11111, "camera").base_url == "http://[::1]:11111"


# ---------------------------------------------------------------------------
# Mount: nudges in sky directions, whichever side of the pier
# ---------------------------------------------------------------------------

_SCOPE = {
    "connected": True, "name": "Scope", "equatorialsystem": 1, "canslewasync": True,
    "canpulseguide": True, "axisrates": [{"Minimum": 0, "Maximum": 4.0}],
}


@pytest.mark.parametrize("pier, direction, axis, sign", [
    (0, "W", "0", 1), (0, "E", "0", -1), (0, "N", "1", 1), (0, "S", "1", -1),
    (1, "W", "0", 1), (1, "E", "0", -1), (1, "N", "1", -1), (1, "S", "1", 1),   # flipped: Dec reversed
])
async def test_nudge_directions(pier: int, direction: str, axis: str, sign: int) -> None:
    device = FakeDevice({**_SCOPE, "sideofpier": pier})
    mount = AlpacaMount(client=device.client("telescope"))
    await mount.connect()
    await mount.start_move(direction, "16x")
    member, form = device.puts[-1]
    assert member == "moveaxis" and form["Axis"] == axis
    assert float(form["Rate"]) == pytest.approx(sign * 16 * 360 / 86164.0905)


async def test_nudge_speed_is_capped_by_the_mount() -> None:
    device = FakeDevice({**_SCOPE, "sideofpier": 0, "axisrates": [{"Minimum": 0, "Maximum": 1.5}]})
    mount = AlpacaMount(client=device.client("telescope"))
    await mount.connect()
    await mount.start_move("W", "800x")
    assert float(device.puts[-1][1]["Rate"]) == pytest.approx(1.5)


async def test_a_mount_that_cannot_move_by_hand() -> None:
    device = FakeDevice({**_SCOPE, "canmoveaxis0": False, "canmoveaxis1": False})
    mount = AlpacaMount(client=device.client("telescope"))
    await mount.connect()
    with pytest.raises(ValueError, match="cannot be moved"):
        await mount.start_move("N", "16x")
    await mount.stop_move()                             # nothing to stop: no request
    assert all(m != "moveaxis" for m, _ in device.puts)


async def test_j2000_mount_gets_j2000_coordinates() -> None:
    import astropy.units as u
    from astropy.coordinates import SkyCoord

    device = FakeDevice({**_SCOPE, "equatorialsystem": 2, "cansync": True})
    mount = AlpacaMount(client=device.client("telescope"))
    await mount.connect()
    await mount.sync(SkyCoord(ra=150 * u.deg, dec=20 * u.deg, frame="icrs"))
    form = device.puts[-1][1]
    assert float(form["RightAscension"]) == pytest.approx(10.0)
    assert float(form["Declination"]) == pytest.approx(20.0)


async def test_failed_connect_leaves_an_error_state() -> None:
    device = FakeDevice({"connected": False})
    # The device acknowledges the PUT but stays disconnected.
    original = device.handler

    def stays_off(request: httpx.Request) -> httpx.Response:
        response = original(request)
        device.values["connected"] = False
        return response
    mount = AlpacaMount(client=AlpacaClient("alpaca.local", 11111, "telescope", 0,
                                            transport=httpx.MockTransport(stays_off)))
    with pytest.raises(AlpacaError, match="did not connect"):
        await mount.connect()
    assert (await mount.get_status()).state == "error"


async def test_disconnecting_stops_a_mount_moving_by_hand() -> None:
    device = FakeDevice({**_SCOPE, "sideofpier": 0})
    mount = AlpacaMount(client=device.client("telescope"))
    await mount.connect()
    await mount.start_move("E", "16x")
    await mount.disconnect()
    stops = [form for member, form in device.puts if member == "moveaxis" and float(form["Rate"]) == 0]
    assert {form["Axis"] for form in stops} == {"0", "1"}
    assert device.puts[-1][0] == "connected"          # stopped first, then let go


async def test_a_slew_stops_moving_by_hand_first() -> None:
    import astropy.units as u
    from astropy.coordinates import SkyCoord

    device = FakeDevice({**_SCOPE, "sideofpier": 0, "slewing": False, "atpark": False})
    mount = AlpacaMount(client=device.client("telescope"))
    await mount.connect()
    await mount.start_move("N", "16x")
    await mount.slew(SkyCoord(ra=10 * u.deg, dec=20 * u.deg, frame="icrs"))
    members = [member for member, _ in device.puts]
    first_stop = next(i for i, (m, f) in enumerate(device.puts) if m == "moveaxis" and float(f["Rate"]) == 0)
    assert first_stop < members.index("slewtocoordinatesasync")
