"""LOCAL upload mode: the saved file is reported through the CCD_FILE_PATH text vector."""
import asyncio
from pathlib import Path

import astrolol._vendor.indipyclient.events as indi_events
import pytest

from astrolol.devices.indi.client import IndiClient


def _file_path_event(device: str, text: str, name: str = "CCD_FILE_PATH") -> indi_events.setTextVector:
    # Built without the XML/device plumbing; rxevent only reads these three attributes.
    event = object.__new__(indi_events.setTextVector)
    event.data = {"FILE_PATH": text}
    event.devicename = device
    event.vectorname = name
    return event


async def _client() -> IndiClient:
    client = IndiClient()
    client._cond = asyncio.Condition()
    return client


async def test_file_path_vector_is_reported_stripped() -> None:
    client = await _client()
    await client.rxevent(_file_path_event("CCD", "\n/tmp/up/img.fits\n"))
    assert await client.wait_for_local_image("CCD", timeout=1) == Path("/tmp/up/img.fits")


async def test_wait_returns_when_path_arrives_later() -> None:
    client = await _client()
    waiter = asyncio.create_task(client.wait_for_local_image("CCD", timeout=2))
    await asyncio.sleep(0.05)
    await client.rxevent(_file_path_event("CCD", "/tmp/up/a.fits"))
    assert await waiter == Path("/tmp/up/a.fits")


async def test_stale_path_is_cleared_before_a_new_exposure() -> None:
    client = await _client()
    await client.rxevent(_file_path_event("CCD", "/tmp/up/old.fits"))
    client.clear_local_image_path("CCD")
    with pytest.raises(Exception):
        await client.wait_for_local_image("CCD", timeout=0.1)


async def test_other_vectors_and_empty_paths_are_ignored() -> None:
    client = await _client()
    await client.rxevent(_file_path_event("CCD", "/tmp/up/x.fits", name="OTHER"))
    await client.rxevent(_file_path_event("CCD", "  "))
    assert client._local_image_paths == {}
