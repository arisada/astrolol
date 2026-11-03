"""Gain is written to whichever property the driver keeps it in, and checked."""
import asyncio
import types
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from astrolol.devices.base.models import ExposureParams
from astrolol.devices.indi import camera as camera_mod
from astrolol.devices.indi.camera import IndiCamera
from astrolol.devices.indi.client import IndiClient


def _vector(values: dict[str, float], labels: dict[str, str] | None = None, perm: str = "rw"):
    labels = labels or {}
    members = {n: types.SimpleNamespace(label=labels.get(n, n), value=v) for n, v in values.items()}
    return types.SimpleNamespace(vectortype="NumberVector", perm=perm, data=members)


class FakeClient:
    """The few IndiClient members the gain code touches, over a dict of vectors."""

    find_number = IndiClient.find_number
    get_number_nowait = IndiClient.get_number_nowait

    def __init__(self, props: dict, *, clamp: float | None = None, ignore_writes: bool = False) -> None:
        self.data = {"CCD": types.SimpleNamespace(data=props)}
        self.clamp = clamp
        self.ignore_writes = ignore_writes
        self.writes: list[tuple[str, dict]] = []

    def _get_vector(self, device: str, prop: str):
        return self.data[device].data.get(prop)

    async def set_number(self, device: str, prop: str, values: dict[str, float]) -> None:
        self.writes.append((prop, values))
        if self.ignore_writes:
            return
        for name, value in values.items():
            if self.clamp is not None:
                value = min(value, self.clamp)
            self.data[device].data[prop].data[name].value = value


# vector.getfloatvalue is what get_number_nowait calls
def _with_getfloat(vec):
    vec.getfloatvalue = lambda element, v=vec: v.data[element].value
    return vec


def _zwo_props():
    return {
        "CCD_EXPOSURE": _with_getfloat(_vector({"CCD_EXPOSURE_VALUE": 0.0})),
        "CCD_CONTROLS": _with_getfloat(_vector({"Gain": 200.0, "Offset": 10.0})),
    }


def _generic_props():
    return {"CCD_GAIN": _with_getfloat(_vector({"GAIN": 90.0}))}


def _events(logs: list[dict]) -> list[str]:
    return [e["event"] for e in logs if e["log_level"] == "warning"]


def _camera(client: FakeClient) -> IndiCamera:
    return IndiCamera("CCD", client, images_dir=Path("/tmp"))  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(camera_mod, "_GAIN_CONFIRM_INTERVAL", 0.0)


async def test_zwo_gain_goes_to_ccd_controls_and_leaves_offset_alone() -> None:
    client = FakeClient(_zwo_props())
    cam = _camera(client)

    await cam._apply_gain(111)

    assert client.writes == [("CCD_CONTROLS", {"Gain": 111.0})]
    assert cam._read_gain() == 111.0
    assert client.data["CCD"].data["CCD_CONTROLS"].data["Offset"].value == 10.0


async def test_other_cameras_keep_using_ccd_gain() -> None:
    client = FakeClient(_generic_props())
    cam = _camera(client)

    await cam._apply_gain(120)

    assert client.writes == [("CCD_GAIN", {"GAIN": 120.0})]
    assert cam._read_gain() == 120.0


async def test_a_property_called_gain_under_another_name_is_found_by_its_label() -> None:
    props = {"CCD_SENSOR": _with_getfloat(_vector({"G": 5.0}, labels={"G": "Gain"}))}
    client = FakeClient(props)

    await _camera(client)._apply_gain(30)

    assert client.writes == [("CCD_SENSOR", {"G": 30.0})]


async def test_a_read_only_gain_is_not_written() -> None:
    props = {"CCD_GAIN": _with_getfloat(_vector({"GAIN": 90.0}, perm="ro"))}
    client = FakeClient(props)

    with capture_logs() as logs:
        await _camera(client)._apply_gain(120)

    assert client.writes == []
    assert _events(logs) == ["indi.camera_gain_unsupported"]


async def test_a_camera_without_gain_warns() -> None:
    client = FakeClient({"CCD_EXPOSURE": _with_getfloat(_vector({"CCD_EXPOSURE_VALUE": 0.0}))})
    cam = _camera(client)

    with capture_logs() as logs:
        await cam._apply_gain(111)

    assert _events(logs) == ["indi.camera_gain_unsupported"]
    assert cam._read_gain() is None


async def test_a_gain_the_driver_did_not_take_is_reported() -> None:
    """The failure of 2026-10-28: frames said 111 but were shot at 200, with nothing in the log."""
    client = FakeClient(_zwo_props(), ignore_writes=True)

    with capture_logs() as logs:
        await _camera(client)._apply_gain(111)

    assert _events(logs) == ["indi.camera_gain_not_applied"]
    assert (logs[0]["requested"], logs[0]["applied"]) == (111, 200.0)


async def test_a_gain_clamped_by_the_driver_is_reported_with_the_real_value() -> None:
    client = FakeClient(_zwo_props(), clamp=100.0)
    cam = _camera(client)

    with capture_logs() as logs:
        await cam._apply_gain(500)

    assert _events(logs) == ["indi.camera_gain_not_applied"]
    assert (logs[0]["requested"], logs[0]["applied"]) == (500, 100.0)
    assert cam._read_gain() == 100.0


async def test_a_gain_that_was_applied_does_not_warn() -> None:
    with capture_logs() as logs:
        await _camera(FakeClient(_zwo_props()))._apply_gain(111)

    assert logs == []


async def test_a_refused_write_is_logged_and_does_not_stop_the_exposure() -> None:
    client = FakeClient(_zwo_props())

    async def refuse(*_a, **_k):
        raise RuntimeError("driver said no")

    client.set_number = refuse  # type: ignore[method-assign]
    with capture_logs() as logs:
        await _camera(client)._apply_gain(111)

    assert _events(logs) == ["indi.camera_gain_failed"]


def test_exposure_params_gain_is_optional() -> None:
    assert ExposureParams(duration=1.0).gain is None


# --- abort ---

class AbortClient(FakeClient):
    """Adds what expose()/abort() use: the exposure state, a frame wait, and the abort switch."""

    def __init__(self, *, obeys_abort: bool) -> None:
        super().__init__(_zwo_props())
        self.obeys_abort = obeys_abort
        self.exposure_state = "Busy"
        self.aborts = 0
        self.frame = None   # asyncio.Event set when the driver delivers

    def _vector_state(self, device: str, prop: str):
        return self.exposure_state

    async def set_switch(self, device: str, prop: str, on: list[str]) -> None:
        self.aborts += 1
        if self.obeys_abort:
            self.exposure_state = "Idle"


@pytest.fixture
def quick(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(camera_mod, "_ABORT_GRACE", 0.3)
    monkeypatch.setattr(camera_mod, "_ABORT_RETRY", 0.1)
    monkeypatch.setattr(camera_mod, "_LATE_FRAME_GRACE", 0.0)


async def test_abort_ends_the_exposure_that_is_waiting(quick) -> None:
    from astrolol.core.errors import ExposureHalted

    cam = _camera(AbortClient(obeys_abort=True))
    hung = asyncio.Event()
    waiting = asyncio.create_task(cam._wait_unless_aborted(hung.wait()))
    await asyncio.sleep(0.05)

    await cam.abort()

    with pytest.raises(ExposureHalted):
        await waiting
    assert cam._abandoned_until == 0.0


async def test_next_exposure_waits_for_a_driver_that_ignored_abort(quick) -> None:
    client = AbortClient(obeys_abort=False)
    cam = _camera(client)

    await cam.abort()                       # the driver carries on
    assert cam._abandoned_until > 0
    asyncio.get_running_loop().call_later(0.5, lambda: setattr(client, "exposure_state", "Ok"))

    t0 = asyncio.get_running_loop().time()
    await cam._settle_aborted_exposure()

    assert asyncio.get_running_loop().time() - t0 >= 0.4
    assert client.aborts >= 3               # asked again while waiting
    assert cam._abandoned_until == 0.0


async def test_no_wait_when_the_driver_obeyed_abort(quick) -> None:
    client = AbortClient(obeys_abort=True)
    cam = _camera(client)
    await cam.abort()
    t0 = asyncio.get_running_loop().time()
    await cam._settle_aborted_exposure()
    assert asyncio.get_running_loop().time() - t0 < 0.1
