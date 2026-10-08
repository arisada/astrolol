import numpy as np
import pytest

from astrolol.devices.base import StreamParams
from astrolol.devices.indi.camera import IndiCamera


class FakeClient:
    def __init__(self, x=10, y=20, w=4, h=3) -> None:
        self.vals = {"X": x, "Y": y, "WIDTH": w, "HEIGHT": h}

    def get_number_nowait(self, dev, prop, element):  # noqa: ANN001
        return self.vals.get(element)


def streaming_camera(**kw) -> IndiCamera:
    cam = IndiCamera("Cam", FakeClient(**kw))  # type: ignore[arg-type]
    cam._stream_params = StreamParams(exposure=0.5, gain=7, binning=2)
    return cam


def test_8bit_frame_is_decoded_with_roi_origin() -> None:
    cam = streaming_camera()
    sub = cam.subscribe_frames()
    cam._on_stream_blob(bytes(range(12)), ".stream")
    frame = sub._frame
    assert frame is not None
    assert frame.pixels.dtype == np.uint8 and frame.pixels.shape == (3, 4)
    assert frame.pixels[2, 3] == 11
    assert frame.origin == (10, 20) and frame.seq == 1
    assert (frame.exposure, frame.gain, frame.binning) == (0.5, 7, 2)


def test_16bit_frame_is_little_endian() -> None:
    cam = streaming_camera()
    sub = cam.subscribe_frames()
    cam._on_stream_blob(np.arange(12, dtype="<u2").tobytes() , ".stream")
    assert sub._frame is not None and sub._frame.pixels.dtype == np.dtype("<u2")
    assert sub._frame.pixels[0, 1] == 1


@pytest.mark.parametrize("size", [11, 13, 36])  # not a whole number of pixels / 3 bytes each
def test_malformed_frames_are_dropped(size) -> None:
    cam = streaming_camera()
    sub = cam.subscribe_frames()
    cam._on_stream_blob(bytes(size), ".stream")
    assert sub._frame is None


def test_frames_after_stop_are_ignored() -> None:
    cam = streaming_camera()
    sub = cam.subscribe_frames()
    cam._stream_params = None
    cam._on_stream_blob(bytes(12), ".stream")
    assert sub._frame is None


async def test_expose_refused_while_streaming() -> None:
    from astrolol.devices.base import ExposureParams

    with pytest.raises(RuntimeError, match="streaming"):
        await streaming_camera().expose(ExposureParams(duration=1))
