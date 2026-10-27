"""IndiClient behaviour that INDIGO servers rely on (tests/integration/test_indigo_simulators.py
runs the same against a real server)."""
import asyncio

import indipyclient.events as indi_events
import pytest

from astrolol.devices.indi.client import IndiClient


def _blob_event(data: dict[str, bytes]) -> indi_events.setBLOBVector:
    # Built without the XML/device plumbing; rxevent only reads these attributes.
    event = object.__new__(indi_events.setBLOBVector)
    event.devicename, event.vectorname = "CCD", "CCD1"
    event.data = data
    event.sizeformat = {name: (len(value), ".fits") for name, value in data.items()}
    return event


async def _client() -> IndiClient:
    client = IndiClient()
    client._cond = asyncio.Condition()
    return client


async def test_an_empty_blob_is_not_an_image() -> None:
    client = await _client()
    seen: list[bytes] = []
    client.add_blob_listener("CCD", "CCD1", lambda data, fmt: seen.append(data))
    await client.rxevent(_blob_event({}))  # INDIGO's "exposure started"
    assert client._blob_versions == {}
    await client.rxevent(_blob_event({"CCD1": b"SIMPLE"}))
    assert client._blob_versions == {("CCD", "CCD1"): 1}
    assert seen == [b"SIMPLE"]


class _Connection:
    def __init__(self, state: str, connect: str) -> None:
        self.state = state
        self._members = {"CONNECT": connect, "DISCONNECT": "Off" if connect == "On" else "On"}

    def __getitem__(self, name: str) -> str:
        return self._members[name]


class _ConnectingClient(IndiClient):
    def __init__(self, connection: _Connection) -> None:
        super().__init__()
        self._cond = asyncio.Condition()
        self.connection = connection
        self.switches: list[list[str]] = []

    async def wait_for_property(self, device_name, prop_name, timeout=10.0):  # noqa: ANN001, ANN201
        return self.connection

    def _get_vector(self, device_name, prop_name):  # noqa: ANN001, ANN202
        return self.connection

    async def set_switch(self, device_name, prop_name, on_elements):  # noqa: ANN001
        self.switches.append(on_elements)
        self.connection.state, self.connection._members["CONNECT"] = "Ok", "On"


async def test_connect_is_not_resent_to_a_connected_device() -> None:
    # INDIGO drivers do not answer it, so waiting for the answer would time out.
    client = _ConnectingClient(_Connection("Ok", "On"))
    await client.connect_device("Mount", conn_timeout=0.5)
    assert client.switches == []


@pytest.mark.parametrize("state, connect", [("Idle", "Off"), ("Alert", "On"), ("Busy", "On")])
async def test_connect_is_sent_otherwise(state: str, connect: str) -> None:
    client = _ConnectingClient(_Connection(state, connect))
    await client.connect_device("Mount", conn_timeout=0.5)
    assert client.switches == [["CONNECT"]]


async def test_a_set_vector_without_timeout_keeps_the_connection() -> None:
    # INDIGO never puts a timeout on set vectors. indipyclient took the missing value as None,
    # and the next send of that vector crashed its keep-alive check, closing the connection
    # (an exposure in flight then never got its image). vendor/indipyclient/PATCHES.md, 3.
    received: list[bytes] = []
    closed = asyncio.Event()

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.read(1024)                                  # getProperties
        writer.write(
            b'<defNumberVector device="CCD" name="CCD_EXPOSURE" state="Idle" perm="rw" timeout="60">'
            b'<defNumber name="CCD_EXPOSURE_VALUE" format="%g" min="0" max="3600" step="1">0</defNumber>'
            b'</defNumberVector>'
            b'<setNumberVector device="CCD" name="CCD_EXPOSURE" state="Ok">'
            b'<oneNumber name="CCD_EXPOSURE_VALUE">0</oneNumber></setNumberVector>'
        )
        await writer.drain()
        while data := await reader.read(4096):
            received.append(data)
        closed.set()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = IndiClient(host="127.0.0.1", port=port)
    try:
        await client.connect()
        await client.wait_for_property("CCD", "CCD_EXPOSURE", timeout=5.0)
        await asyncio.sleep(0.3)                                 # the set vector arrives
        await client.set_number("CCD", "CCD_EXPOSURE", {"CCD_EXPOSURE_VALUE": 1.0})
        await asyncio.sleep(1.5)                                 # the check runs every 0.5 s
        assert any(b"newNumberVector" in d for d in received)
        assert not closed.is_set()
        assert client.connected
    finally:
        await client.disconnect()
        server.close()
