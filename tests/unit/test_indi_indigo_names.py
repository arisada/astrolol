"""The INDI adapters use INDIGO's names where an INDIGO server does not translate them.

tests/integration/test_indigo_simulators.py checks the same against INDIGO's simulators.
"""
from __future__ import annotations

import pytest

from astrolol.devices.base.models import TrackingMode
from astrolol.devices.indi.camera import IndiCamera
from astrolol.devices.indi.focuser import IndiFocuser
from astrolol.devices.indi.mount import IndiMount


class _Vector:
    def __init__(self, vectortype: str) -> None:
        self.vectortype = vectortype


class _FakeClient:
    def __init__(self, vectors: dict[str, str], numbers: dict[tuple[str, str], float] | None = None) -> None:
        self.vectors = {name: _Vector(t) for name, t in vectors.items()}
        self.numbers = numbers or {}
        self.sent: list[tuple[str, object]] = []

    def _get_vector(self, device: str, prop: str) -> _Vector | None:
        return self.vectors.get(prop)

    def get_number_nowait(self, device: str, prop: str, element: str) -> float | None:
        return self.numbers.get((prop, element))

    def get_switch_state_nowait(self, device: str, prop: str, element: str) -> bool | None:
        return None

    async def set_switch(self, device: str, prop: str, on: list[str]) -> None:
        self.sent.append((prop, on))

    async def set_number(self, device: str, prop: str, values: dict) -> None:
        self.sent.append((prop, values))


@pytest.mark.parametrize("vectors, expected", [
    ({"TELESCOPE_TRACK_MODE": "SwitchVector"}, "TELESCOPE_TRACK_MODE"),
    # INDI's TELESCOPE_TRACK_RATE is a custom-rate number: never the rate switch.
    ({"TELESCOPE_TRACK_MODE": "SwitchVector", "TELESCOPE_TRACK_RATE": "NumberVector"}, "TELESCOPE_TRACK_MODE"),
    ({"TELESCOPE_TRACK_RATE": "NumberVector"}, "TELESCOPE_TRACK_MODE"),
    ({"TELESCOPE_TRACK_RATE": "SwitchVector"}, "TELESCOPE_TRACK_RATE"),   # INDIGO
])
async def test_tracking_rate_switch(vectors: dict[str, str], expected: str) -> None:
    client = _FakeClient(vectors)
    mount = IndiMount(device_name="Mount", client=client)  # type: ignore[arg-type]
    await mount.set_tracking(True, TrackingMode.LUNAR)
    assert client.sent[0] == (expected, ["TRACK_LUNAR"])


@pytest.mark.parametrize("vectors, expected", [
    ({"SCOPE_INFO": "NumberVector"}, "SCOPE_INFO"),
    ({"CCD_LENS": "NumberVector"}, "CCD_LENS"),                         # INDIGO
    ({"SCOPE_INFO": "NumberVector", "CCD_LENS": "NumberVector"}, "SCOPE_INFO"),
])
async def test_scope_info_property(vectors: dict[str, str], expected: str, tmp_path) -> None:
    client = _FakeClient(vectors)
    camera = IndiCamera(device_name="Cam", client=client, images_dir=tmp_path)  # type: ignore[arg-type]
    await camera.push_scope_info(800.0, 150.0)
    assert client.sent == [(expected, {"FOCAL_LENGTH": 800.0, "APERTURE": 150.0})]


@pytest.mark.parametrize("prop", ["FOCUS_TEMPERATURE", "FOCUSER_TEMPERATURE"])
async def test_focuser_temperature(prop: str) -> None:
    client = _FakeClient({prop: "NumberVector"}, {(prop, "TEMPERATURE"): 12.5})
    focuser = IndiFocuser(device_name="Focuser", client=client)  # type: ignore[arg-type]
    assert (await focuser.get_status()).temperature == 12.5
