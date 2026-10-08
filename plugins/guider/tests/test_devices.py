import pytest

from astrolol.core.guiding.errors import GuiderNotConnected
from astrolol.imaging.streaming import LoopingExposureStream
from plugins.guider.devices import ManagerDevices
from plugins.guider.settings import GuiderSettings
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
