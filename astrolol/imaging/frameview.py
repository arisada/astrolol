"""What a camera sees right now, ready to show: a stretched JPEG, frame statistics and the
stars to draw over it. Shared by the guider and the polar-alignment star view."""

from __future__ import annotations

import io
from typing import Literal

import numpy as np
from PIL import Image
from pydantic import BaseModel

from astrolol.devices.base.streaming import Frame

StarKind = Literal["primary", "companion", "candidate", "lost"]


class OverlayStar(BaseModel):
    x: float  # sensor coordinates (binned pixels)
    y: float
    kind: StarKind
    snr: float | None = None
    fwhm: float | None = None
    hfd: float | None = None  # half-flux diameter, pixels
    peak: float | None = None  # brightest pixel above the background
    flux: float | None = None
    half: int = 8  # half-size of the window the tracker measures
    saturated: bool = False
    state: Literal["ok", "blurred", "lost", "outlier"] | None = None  # while guiding


class FrameStats(BaseModel):
    """What a frame looks like, apart from its stars."""

    seq: int
    exposure: float  # seconds
    period: float | None = None  # seconds between frames as observed
    background: float  # median level, ADU
    noise: float  # robust spread of the background, ADU
    brightest: float  # brightest pixel, ADU


def frame_stats(frame: Frame, period: float | None = None) -> FrameStats:
    sample = frame.pixels[:: max(1, frame.height // 128), :: max(1, frame.width // 128)].astype(np.float32)
    background = float(np.median(sample))
    noise = float(1.4826 * np.median(np.abs(sample - background)))
    return FrameStats(
        seq=frame.seq, exposure=frame.exposure, period=period or None,
        background=background, noise=noise, brightest=float(frame.pixels.max()),
    )


# A sky spanning fewer ADU than this is noise from the quantisation, not from photons.
LOW_RANGE_ADU = 12.0


def render_jpeg(pixels: np.ndarray, max_width: int = 960, quality: int = 80) -> bytes:
    """A stretched 8-bit JPEG: star fields are mostly dark, so the range is cut at the
    background and a bright percentile, and compressed with a square root.

    Low-range frames (an 8-bit stream: background 0-2, a star at 10-60) need care: cutting
    at the 99.8th percentile would stretch the quantisation noise of the sky to full contrast
    and bury the stars. The range is therefore never narrower than a few noise levels (at
    least one ADU: integers have no finer noise) and, when the sky itself spans only a few
    ADU, reaches up to a share of the brightest star.
    """
    img = pixels.astype(np.float32)
    sample = img[:: max(1, img.shape[0] // 256), :: max(1, img.shape[1] // 256)]
    background = float(np.median(sample))
    sigma = max(float(1.4826 * np.median(np.abs(sample - background))), 1.0)
    lo = min(float(np.percentile(sample, 5)), background)
    hi = max(float(np.percentile(sample, 99.8)), lo + 8 * sigma)
    peak = float(img.max())
    if hi - lo < LOW_RANGE_ADU and peak - background > hi - lo:
        lo, hi = background, max(hi, background + 0.3 * (peak - background))
    scaled = np.sqrt(np.clip((img - lo) / (hi - lo), 0.0, 1.0))
    image = Image.fromarray((scaled * 255).astype(np.uint8), mode="L")
    if image.width > max_width:
        image = image.reduce(-(-image.width // max_width))
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()
