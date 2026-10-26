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
