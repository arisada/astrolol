"""What the real camera writes in its own FITS files and the stream does not carry.

A stream frame is bare pixels: no Bayer pattern, no pixel size, no camera name. One very short
ordinary exposure, taken while the camera is idle, returns the driver's usual FITS; the few cards
that describe the camera (not the exposure) are kept and copied into every stack.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import astropy.io.fits as astropy_fits
import structlog

from astrolol.devices.base.models import ExposureParams

logger = structlog.get_logger()

# Short enough to cost nothing, long enough for every driver: the INDI CCD simulator never
# answers a 1 ms exposure, and a camera that hangs must not hold up connecting (30 s at most).
PROBE_EXPOSURE = 0.05
PROBE_TIMEOUT = 12.0

# Cards that describe the camera. Anything about the exposure itself (time, gain, temperature,
# size) is left out: the stack sets those.
_PATTERN_CARDS = ("BAYERPAT", "XBAYROFF", "YBAYROFF")
_PLAIN_CARDS = ("ROWORDER", "INSTRUME")


@dataclass(frozen=True)
class CameraCards:
    """The camera's cards as for unbinned frames, with the pixel size per unbinned pixel."""

    cards: dict[str, tuple[object, str]]
    pixel_width: float | None = None  # µm, unbinned
    pixel_height: float | None = None

    def for_binning(self, binning: int) -> dict[str, tuple[object, str]]:
        found = dict(self.cards)
        if binning > 1:  # binned colour pixels mix the filters: there is no pattern left
            for key in _PATTERN_CARDS:
                found.pop(key, None)
        if self.pixel_width is not None:
            found["XPIXSZ"] = (self.pixel_width * binning, "[um] pixel width, binned")
        if self.pixel_height is not None:
            found["YPIXSZ"] = (self.pixel_height * binning, "[um] pixel height, binned")
        return found


def read_cards(path: str | Path) -> CameraCards | None:
    """The camera cards of a FITS file taken with no binning; None when it has none."""
    with astropy_fits.open(path) as hdus:
        header = hdus[0].header
        binning_x = max(1, int(header.get("XBINNING", 1) or 1))
        binning_y = max(1, int(header.get("YBINNING", binning_x) or 1))
        cards: dict[str, tuple[object, str]] = {}
        for key in (*_PATTERN_CARDS, *_PLAIN_CARDS):
            if key in header:
                cards[key] = (header[key], header.comments[key])
        width = header.get("XPIXSZ")
        height = header.get("YPIXSZ")
        pixel_width = float(width) / binning_x if width else None
        pixel_height = float(height) / binning_y if height else None
    if not cards and pixel_width is None and pixel_height is None:
        return None
    return CameraCards(cards, pixel_width, pixel_height)


async def probe_camera(camera: Any, timeout: float = PROBE_TIMEOUT) -> CameraCards | None:
    """Take a very short exposure with *camera* (idle) and keep its camera cards.

    Best effort: a camera that cannot do it, or takes too long, simply yields no cards.
    """
    try:
        image = await asyncio.wait_for(
            camera.expose(ExposureParams(duration=PROBE_EXPOSURE, binning=1)), timeout
        )
    except TimeoutError:
        logger.warning("stacked_camera.probe_timeout", seconds=timeout)
        with contextlib.suppress(Exception):
            await camera.abort()
        return None
    except Exception as exc:
        logger.warning("stacked_camera.probe_failed", error=str(exc))
        return None
    path = Path(image.fits_path)
    try:
        return await asyncio.to_thread(read_cards, path)
    except Exception as exc:
        logger.warning("stacked_camera.probe_unreadable", error=str(exc))
        return None
    finally:
        with contextlib.suppress(OSError):
            path.unlink()
