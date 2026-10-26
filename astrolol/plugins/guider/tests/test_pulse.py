import pytest

from astrolol.devices.base import IPulseGuider, PulseGuideNotSupported
from astrolol.devices.indi.pulse import (
    connect_guide_companion,
    disconnect_guide_companion,
    has_pulse_guide,
    indi_pulse_guide,
    pulse_device,
)
from astrolol.plugins.guider.settings import GuiderSettings, pick_pulse_guider


class FakeClient:
    def __init__(self, props: set[str]) -> None:
        self.props = props
        self.sent: list[tuple[str, str, dict[str, float]]] = []
        self.waited: list[tuple[str, float]] = []

    def _get_vector(self, device: str, prop: str):  # noqa: ANN202
        return object() if prop in self.props else None

    async def set_number(self, device: str, prop: str, values: dict[str, float]) -> None:
        self.sent.append((device, prop, values))

    async def wait_prop_busy_then_done(self, device, prop, busy_timeout, done_timeout) -> None:  # noqa: ANN001
        self.waited.append((prop, done_timeout))


ST4 = {"TELESCOPE_TIMED_GUIDE_NS", "TELESCOPE_TIMED_GUIDE_WE"}


@pytest.mark.parametrize(
    "direction, prop, expected",
    [
        ("N", "TELESCOPE_TIMED_GUIDE_NS", {"TIMED_GUIDE_N": 250.0, "TIMED_GUIDE_S": 0.0}),
        ("S", "TELESCOPE_TIMED_GUIDE_NS", {"TIMED_GUIDE_S": 250.0, "TIMED_GUIDE_N": 0.0}),
        ("E", "TELESCOPE_TIMED_GUIDE_WE", {"TIMED_GUIDE_E": 250.0, "TIMED_GUIDE_W": 0.0}),
        ("W", "TELESCOPE_TIMED_GUIDE_WE", {"TIMED_GUIDE_W": 250.0, "TIMED_GUIDE_E": 0.0}),
    ],
)
async def test_pulse_writes_one_direction_and_waits(direction, prop, expected) -> None:
    client = FakeClient(ST4)
    await indi_pulse_guide(client, "Cam", direction, 250)  # type: ignore[arg-type]
    assert client.sent == [("Cam", prop, expected)]
    assert client.waited == [(prop, pytest.approx(5.25))]


async def test_pulse_without_the_property_is_unsupported() -> None:
    client = FakeClient(set())
    assert not has_pulse_guide(client, "Cam")  # type: ignore[arg-type]
    with pytest.raises(PulseGuideNotSupported):
        await indi_pulse_guide(client, "Cam", "N", 100)  # type: ignore[arg-type]
    assert client.sent == []


@pytest.mark.parametrize("ms", [0, -5])
async def test_pulse_rejects_non_positive_duration(ms) -> None:
    with pytest.raises(ValueError):
        await indi_pulse_guide(FakeClient(ST4), "Cam", "N", ms)  # type: ignore[arg-type]


class Guideable:
    async def pulse_guide(self, direction, duration_ms) -> None:  # noqa: ANN001
        pass


def test_camera_is_the_default_output() -> None:
    assert GuiderSettings().guide_output == "camera"


def test_pick_follows_the_setting() -> None:
    cam, mount = Guideable(), Guideable()
    assert pick_pulse_guider("camera", cam, mount) is cam
    assert pick_pulse_guider("mount", cam, mount) is mount
    assert isinstance(cam, IPulseGuider)


@pytest.mark.parametrize("output, cam, mount", [
    ("camera", None, Guideable()),      # chosen device missing
    ("mount", Guideable(), object()),   # chosen device can't pulse
])
def test_pick_refuses_a_device_that_cannot_pulse(output, cam, mount) -> None:
    with pytest.raises(PulseGuideNotSupported):
        pick_pulse_guider(output, cam, mount)


class CompanionClient(FakeClient):
    """Pulse properties live on '<device> (guider)', as INDIGO drivers publish them."""

    def __init__(self, device_props: dict[str, set[str]]) -> None:
        super().__init__(set())
        self.device_props = device_props
        self.connected: list[str] = []
        self.disconnected: list[str] = []

    def _get_vector(self, device: str, prop: str):  # noqa: ANN202
        return object() if prop in self.device_props.get(device, set()) else None

    def list_devices(self) -> list[str]:
        return list(self.device_props)

    async def connect_device(self, device: str) -> None:
        self.connected.append(device)

    async def disconnect_device(self, device: str) -> None:
        self.disconnected.append(device)


async def test_pulse_goes_to_the_guide_companion() -> None:
    client = CompanionClient({"Mount": set(), "Mount (guider)": ST4})
    assert pulse_device(client, "Mount") == "Mount (guider)"  # type: ignore[arg-type]
    await indi_pulse_guide(client, "Mount", "W", 100)  # type: ignore[arg-type]
    assert client.sent == [("Mount (guider)", "TELESCOPE_TIMED_GUIDE_WE", {"TIMED_GUIDE_W": 100.0, "TIMED_GUIDE_E": 0.0})]


async def test_the_device_itself_wins_over_a_companion() -> None:
    client = CompanionClient({"Mount": ST4, "Mount (guider)": ST4})
    assert pulse_device(client, "Mount") == "Mount"  # type: ignore[arg-type]


async def test_companion_is_connected_and_disconnected_only_if_it_exists() -> None:
    client = CompanionClient({"Mount": ST4, "Mount (guider)": set(), "Cam": set()})
    await connect_guide_companion(client, "Mount")  # type: ignore[arg-type]
    await connect_guide_companion(client, "Cam")  # type: ignore[arg-type]
    await disconnect_guide_companion(client, "Mount")  # type: ignore[arg-type]
    await disconnect_guide_companion(client, "Cam")  # type: ignore[arg-type]
    assert client.connected == ["Mount (guider)"]
    assert client.disconnected == ["Mount (guider)"]
