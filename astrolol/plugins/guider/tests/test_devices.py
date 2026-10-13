import pytest

from astrolol.core.guiding.errors import GuiderNotConnected
from astrolol.imaging.streaming import LoopingExposureStream
from astrolol.plugins.guider.devices import ManagerDevices
from astrolol.plugins.guider.settings import GuiderSettings
from tests.conftest import FakeCamera, FakeMount


class Manager:
    def __init__(self, **devices: object) -> None:
        self.devices = devices

    def get_camera(self, device_id: str) -> object:
        return self.devices[device_id]

    get_mount = get_camera


class Pulser:
    async def pulse_guide(self, direction, duration_ms) -> None:  # noqa: ANN001
        pass


class StreamingPulser(Pulser):
    can_stream = True

    async def start_stream(self, params) -> None: ...  # noqa: ANN001
    async def stop_stream(self) -> None: ...
    def subscribe_frames(self): ...  # noqa: ANN201


def devices(settings: GuiderSettings, **managed: object) -> ManagerDevices:
    return ManagerDevices(Manager(**managed), lambda: settings)


def test_no_camera_chosen_is_a_clear_error() -> None:
    with pytest.raises(GuiderNotConnected, match="Choose the guide camera"):
        devices(GuiderSettings()).camera()


def test_camera_not_connected() -> None:
    with pytest.raises(GuiderNotConnected, match="not connected"):
        devices(GuiderSettings(camera_id="cam"), other=object()).camera()


def test_native_stream_is_used_as_is() -> None:
    cam = StreamingPulser()
    assert devices(GuiderSettings(camera_id="cam"), cam=cam).camera() is cam


def test_camera_without_a_stream_is_wrapped_once(tmp_path) -> None:
    d = devices(GuiderSettings(camera_id="cam"), cam=FakeCamera(tmp_path))
    first = d.camera()
    assert isinstance(first, LoopingExposureStream) and d.camera() is first


def test_camera_whose_driver_cannot_stream_is_wrapped() -> None:
    cam = StreamingPulser()
    cam.can_stream = False
    assert isinstance(devices(GuiderSettings(camera_id="cam"), cam=cam).camera(), LoopingExposureStream)


def test_camera_output_uses_the_camera() -> None:
    cam = StreamingPulser()
    d = devices(GuiderSettings(camera_id="cam", guide_output="camera"), cam=cam, mount=Pulser())
    assert d.pulse_guider() is cam


def test_mount_output_uses_the_mount() -> None:
    mount = Pulser()
    d = devices(GuiderSettings(camera_id="cam", mount_id="mount", guide_output="mount"), cam=StreamingPulser(), mount=mount)
    assert d.pulse_guider() is mount


def test_mount_output_needs_a_mount_chosen() -> None:
    d = devices(GuiderSettings(camera_id="cam", guide_output="mount"), cam=StreamingPulser())
    with pytest.raises(GuiderNotConnected, match="Choose the mount"):
        d.pulse_guider()


def test_a_device_that_cannot_pulse_is_reported(tmp_path) -> None:
    d = devices(GuiderSettings(camera_id="cam", guide_output="camera"), cam=FakeCamera(tmp_path))
    with pytest.raises(GuiderNotConnected, match="cannot pulse guide"):
        d.pulse_guider()


# --- what the guider reads from the mount ---

class ListingManager(Manager):
    def list_connected(self) -> list[dict]:
        return [{"device_id": k, "kind": "mount" if isinstance(v, FakeMount) else "camera"} for k, v in self.devices.items()]


async def test_mount_state_reads_pointing_and_pier_side() -> None:
    from astropy.coordinates import SkyCoord
    import astropy.units as u

    mount = FakeMount()
    await mount.connect()
    await mount.slew(SkyCoord(ra=10 * u.deg, dec=35 * u.deg))
    d = ManagerDevices(ListingManager(cam=StreamingPulser(), mount=mount), lambda: GuiderSettings(camera_id="cam", mount_id="mount"))
    state = await d.mount_state()
    assert state is not None and state.dec == pytest.approx(35, abs=0.5) and state.pier_side == "West"
    assert not state.slewing and not state.parked


async def test_mount_state_uses_the_only_mount_when_none_is_chosen() -> None:
    mount = FakeMount()
    await mount.connect()
    d = ManagerDevices(ListingManager(cam=StreamingPulser(), m=mount), lambda: GuiderSettings(camera_id="cam"))
    assert await d.mount_state() is not None


async def test_no_mount_means_no_state() -> None:
    d = ManagerDevices(ListingManager(cam=StreamingPulser()), lambda: GuiderSettings(camera_id="cam"))
    assert await d.mount_state() is None
    assert await devices(GuiderSettings(camera_id="cam"), cam=StreamingPulser()).mount_state() is None  # no listing


def test_min_move_follows_the_pixel_scale() -> None:
    from astrolol.plugins.guider.settings import auto_min_move_px

    assert auto_min_move_px(None) == 0.15
    assert auto_min_move_px(1.0) == pytest.approx(0.3)
    assert auto_min_move_px(0.3) == 0.5 and auto_min_move_px(6.0) == 0.1
