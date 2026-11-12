"""Camera cards (Bayer pattern, pixel size, name) learnt from one short exposure at connect."""

from __future__ import annotations

import asyncio

import astropy.io.fits as astropy_fits
import pytest

from astrolol.devices.base.models import ExposureParams
from astrolol.plugins.stacked_camera.probe import CameraCards, probe_camera, read_cards
from astrolol.plugins.stacked_camera.tests.rig import Rig, SourceCamera, feed, started

COLOUR = {
    "BAYERPAT": "RGGB",
    "XBAYROFF": 0,
    "YBAYROFF": 1,
    "ROWORDER": "TOP-DOWN",
    "INSTRUME": "ZWO ASI183MC",
    "XPIXSZ": 2.4,
    "YPIXSZ": 2.4,
    "XBINNING": 1,
    "YBINNING": 1,
    "EXPTIME": 0.001,
    "GAIN": 120,
    "CCD-TEMP": 21.0,
}


async def _colour_source(rig: Rig, **header: object) -> SourceCamera:
    source = await rig.source()
    source.probe_header = {**COLOUR, **header}
    source.probe_dir = rig.tmp_path / "probe"
    source.probe_dir.mkdir(exist_ok=True)
    return source


async def _stack(rig: Rig, source: SourceCamera, duration: float = 0.1, binning: int = 1) -> dict:
    stacked = await rig.stacked()
    stacked._images_dir = rig.tmp_path
    task = _expose(stacked, duration, binning)
    await started(source)
    await feed(source, 2, binning=binning)
    image = await task
    return dict(astropy_fits.getheader(image.fits_path))


def _expose(stacked, duration: float, binning: int):  # type: ignore[no-untyped-def]
    import asyncio

    return asyncio.ensure_future(stacked.expose(ExposureParams(duration=duration, binning=binning)))


async def test_connecting_takes_one_short_exposure_and_removes_its_file(rig: Rig) -> None:
    source = await _colour_source(rig)
    await rig.stacked()
    assert source.exposures == [0.05]
    assert list((rig.tmp_path / "probe").iterdir()) == []


async def test_the_second_virtual_camera_reuses_what_was_learnt(rig: Rig) -> None:
    source = await _colour_source(rig)
    await rig.stacked()
    await rig.fast()
    assert source.exposures == [0.05]


async def test_the_stack_carries_the_camera_cards_but_not_the_probe_exposure(rig: Rig) -> None:
    source = await _colour_source(rig)
    header = await _stack(rig, source)
    assert header["BAYERPAT"] == "RGGB"
    assert (header["XBAYROFF"], header["YBAYROFF"]) == (0, 1)
    assert header["INSTRUME"] == "ZWO ASI183MC" and header["ROWORDER"] == "TOP-DOWN"
    assert header["XPIXSZ"] == pytest.approx(2.4)
    assert header["EXPTIME"] == pytest.approx(0.1)  # the stack's, not the probe's 50 ms
    assert header["NSUBS"] == 2
    assert "CCD-TEMP" not in header or header["CCD-TEMP"] != 21.0


async def test_binning_scales_the_pixel_size_and_drops_the_colour_pattern(rig: Rig) -> None:
    source = await _colour_source(rig)
    header = await _stack(rig, source, binning=2)
    assert header["XPIXSZ"] == pytest.approx(4.8) and header["YPIXSZ"] == pytest.approx(4.8)
    assert "BAYERPAT" not in header and "XBAYROFF" not in header
    assert header["INSTRUME"] == "ZWO ASI183MC"


async def test_a_mono_camera_has_no_pattern_to_copy(rig: Rig) -> None:
    source = await _colour_source(rig)
    for key in ("BAYERPAT", "XBAYROFF", "YBAYROFF"):
        del source.probe_header[key]
    header = await _stack(rig, source)
    assert "BAYERPAT" not in header and header["INSTRUME"] == "ZWO ASI183MC"


async def test_a_camera_that_cannot_expose_still_connects_and_stacks(rig: Rig) -> None:
    source = await rig.source()  # no probe_header: expose() refuses
    header = await _stack(rig, source)
    assert "BAYERPAT" not in header and header["NSUBS"] == 2
    assert source.exposures == [0.05]  # tried the longer one too, once


async def test_a_camera_that_hangs_does_not_hold_up_connecting(rig: Rig) -> None:
    class Hangs(SourceCamera):
        aborted = False

        async def expose(self, params: ExposureParams):  # type: ignore[no-untyped-def]
            await asyncio.sleep(30)

        async def abort(self) -> None:
            self.aborted = True

    camera = Hangs()
    assert await probe_camera(camera, timeout=0.05) is None
    assert camera.aborted


async def test_a_replaced_camera_is_learnt_again(rig: Rig) -> None:
    source = await _colour_source(rig)
    fast = await rig.fast()  # the guider's camera: probes at connect, before any stream
    assert source.exposures == [0.05]
    await fast.stop_stream()
    # a camera replaced by a new instance is learnt again
    await rig.manager.disconnect("cam_fast")
    await rig.manager.disconnect("cam")
    source = await _colour_source(rig)
    await rig.fast()
    assert source.exposures == [0.05]


async def test_busy_stream_postpones_the_probe(rig: Rig) -> None:
    source = await rig.source()
    fast = await rig.fast()  # probe tried (and failed) while idle: cached as unknown
    from astrolol.devices.base.streaming import StreamParams

    await fast.start_stream(StreamParams(exposure=0.05))
    await started(source)
    before = list(source.exposures)
    stacked = await rig.stacked()  # connects while the guider streams: must not expose
    assert source.exposures == before
    await fast.stop_stream()
    assert stacked is not None


def test_read_cards_divides_the_pixel_size_by_the_binning(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "x.fits"
    hdu = astropy_fits.PrimaryHDU()
    hdu.header["XBINNING"] = 2
    hdu.header["XPIXSZ"] = 4.8
    hdu.header["YPIXSZ"] = 4.8
    hdu.writeto(path)
    cards = read_cards(path)
    assert cards is not None and cards.pixel_width == pytest.approx(2.4)


def test_a_file_with_no_camera_cards_gives_none(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "x.fits"
    astropy_fits.PrimaryHDU().writeto(path)
    assert read_cards(path) is None


def test_for_binning_leaves_the_original_untouched() -> None:
    cards = CameraCards({"BAYERPAT": ("RGGB", "")}, 2.4, 2.4)
    cards.for_binning(2)
    assert "BAYERPAT" in cards.cards and cards.for_binning(1)["XPIXSZ"][0] == 2.4
