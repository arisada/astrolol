"""
FITS → JPEG preview generators.

Two stretching modes:
- Auto: the screen-transfer-function stretch used by PixInsight (STF), Siril,
  N.I.N.A. and Ekos. The black point sits a few noise σ below the sky background
  (σ from the median absolute deviation), and a midtones transfer function (MTF)
  lifts the background to a target brightness while compressing highlights —
  nothing is clipped at the top. Because both parameters are relative to the
  background and its noise, a given setting looks the same on a sparse star field
  and on a dense nebula, unlike a percentile-based stretch.
- Linear: maps [0, sensor full-scale ADU] to [0, 255] with no per-frame rescaling.
  Unlike auto-stretch (and unlike a naive per-frame min/max stretch, which would
  independently renormalise every frame and hide real brightness differences
  between them), this is anchored to the sensor's fixed ADU range so two frames
  are directly comparable — e.g. two flats shot at different exposures actually
  look different. Useful for sanity-checking true signal level.

Memory model (sized for a Raspberry Pi): the FITS file is memory-mapped and read
in row strips, never decoded as a whole. Each strip is binned k×k (block mean,
k the smallest integer bringing the longest side under the target size) into a
small float32 ``PreviewBase``, and the full-resolution histogram and mean are
accumulated along the way. Peak memory is about one strip plus the base —
instead of the whole frame as uint16, float32 and a PIL copy (~250 MB for a
26 MP sensor). Every rendering (auto, linear, a re-stretch with different
percentiles) is then a cheap pass over the base; ``PreviewBaseCache`` keeps
recent bases so re-stretching never re-reads the FITS file.

The base is float32 rather than uint16 on purpose: binning a low-noise frame
(bias, short dark) averages the noise down below 1 ADU, and rounding back to
integers would posterize the stretched result.

Colour (one-shot-colour) frames are recognised by their BAYERPAT header (with
XBAYROFF/YBAYROFF offsets) and debayered for free during binning: the bin factor
is forced even, so every k×k block holds whole 2×2 Bayer cells, and each colour
site is averaged into its own channel ("superpixel" debayer — no interpolation).
ROWORDER is not consulted: BAYERPAT is taken to describe the data in file order,
which is what INDI writes. Colour bases are stretched per channel by default
("unlinked", which also neutralises a light-pollution colour cast) or with shared
parameters ("linked", true colour balance), or rendered as luminance ("mono").
"""
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from astropy.io import fits
from PIL import Image

_PREVIEW_MAX_DIM = 2000
_HIST_BINS = 128
# Full-resolution pixels per strip. Strip temporaries (float copy, histogram
# indices) are a few bytes per pixel each, so this keeps them to a few MB.
_STRIP_PIXELS = 256 * 1024
# Upper bound on pixels sampled from the base for percentile estimates.
_SAMPLE_TARGET = 250_000
# Pixels at or above this fraction of full scale count as saturated. Slightly
# below 1.0 so 12/14-bit data left-shifted into 16 bits (max 65520/65532) counts.
_SATURATION_FRACTION = 0.995
# σ ≈ 1.4826 · MAD for normally distributed noise.
_MAD_TO_SIGMA = 1.4826

_CHANNEL_NAMES = ("R", "G", "B")

DEFAULT_TARGET_BG = 0.25
DEFAULT_SHADOWS_SIGMA = -2.8


@dataclass(frozen=True)
class PreviewBase:
    """A binned, display-sized copy of a frame plus full-resolution statistics.

    ``data`` must be treated as read-only — it may be shared through a cache.
    """
    data: np.ndarray          # float32 (h // bin, w // bin[, 3 for colour]), physical ADU
    adu_max: float            # sensor full-scale value (see _adu_max)
    histogram: np.ndarray     # _HIST_BINS counts over [0, hist_max], full resolution
    hist_max: float
    mean: float               # full resolution
    full_sample: np.ndarray   # strided full-resolution sample (physical ADU)
    saturated: int | None     # full-resolution count; None without a fixed full scale
    width: int                # original frame size
    height: int
    bin_factor: int
    bayer_pattern: str | None = None             # effective pattern at (0, 0), e.g. "RGGB"
    channel_histograms: np.ndarray | None = None  # (3, _HIST_BINS), colour only
    channel_samples: tuple[np.ndarray, ...] | None = None  # R, G, B full-res samples

    @property
    def is_color(self) -> bool:
        return self.data.ndim == 3

    def luminance(self) -> np.ndarray:
        return self.data.mean(axis=2, dtype=np.float32) if self.is_color else self.data

    def sample(self, channel: int | None = None) -> np.ndarray:
        """Strided sample of the binned data — one channel, or luminance when None."""
        pixels = self.data.reshape(-1, 3) if self.is_color else self.data.reshape(-1)
        picked = pixels[:: max(1, pixels.shape[0] // _SAMPLE_TARGET)]
        if not self.is_color:
            return picked
        return picked[:, channel] if channel is not None else picked.mean(axis=1)


def _bin_factor(height: int, width: int, max_dim: int, bayer: bool = False) -> int:
    k = max(1, math.ceil(max(height, width) / max_dim))
    if bayer and k % 2:
        k += 1  # whole 2×2 Bayer cells per block
    return k


def _bayer_pattern(header: fits.Header) -> str | None:
    """Effective Bayer pattern at array (0, 0), or None for a mono frame.

    BAYERPAT names the pattern starting at (XBAYROFF, YBAYROFF); an odd offset
    shifts which colour sits at the array origin.
    """
    pattern = str(header.get("BAYERPAT", "")).strip().strip("'").upper()
    if len(pattern) != 4 or sorted(pattern) != ["B", "G", "G", "R"]:
        return None
    try:
        xoff = int(header.get("XBAYROFF", 0) or 0) % 2
        yoff = int(header.get("YBAYROFF", 0) or 0) % 2
    except (TypeError, ValueError):
        xoff = yoff = 0
    return "".join(pattern[((py + yoff) % 2) * 2 + (px + xoff) % 2] for py in (0, 1) for px in (0, 1))


def _adu_max(raw: np.ndarray, bzero: float, bscale: float) -> float | None:
    """Full-scale value of the *physical* (BZERO/BSCALE-applied) data type.

    Mirrors what astropy's scaled read would yield: on-disk int16 + BZERO=32768 is
    uint16 → 65535, uint8 → 255, and so on — the same convention imaging software
    like N.I.N.A. uses to judge clipping. Returns None when the physical data is
    not integer-valued (float FITS, or a non-unit BSCALE); the caller then falls
    back to the data's own max, since there is no fixed full-scale value.
    """
    if not np.issubdtype(raw.dtype, np.integer) or bscale != 1 or bzero != int(bzero):
        return None
    return float(np.iinfo(raw.dtype).max) + bzero


def _physical(raw: np.ndarray, bzero: float, bscale: float, work_dtype: type) -> np.ndarray:
    """Convert a raw on-disk strip (big-endian, unscaled) to physical ADU values."""
    out = raw.astype(work_dtype)
    if bscale != 1:
        out *= bscale
    if bzero:
        out += bzero
    if not np.issubdtype(raw.dtype, np.integer):
        np.nan_to_num(out, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
    return out


def _bin_bayer_rows(strip: np.ndarray, k: int, out_w: int, pattern: str) -> np.ndarray:
    """Superpixel-debayer + block-mean a strip (rows a multiple of even *k*) to RGB."""
    rows = strip.shape[0]
    half = k // 2
    # (block row, cell row, row parity, block col, cell col, col parity)
    cells = strip[:, : out_w * k].reshape(rows // k, half, 2, out_w, half, 2)
    sites = cells.mean(axis=(1, 4), dtype=np.float32)  # (rows/k, 2, out_w, 2)
    out = np.zeros((rows // k, out_w, 3), dtype=np.float32)
    for i, colour in enumerate(pattern):
        c = _CHANNEL_NAMES.index(colour)
        site = sites[:, i // 2, :, i % 2]
        out[..., c] += site if colour != "G" else site * np.float32(0.5)
    return out


def _bin_rows(strip: np.ndarray, k: int, out_w: int) -> np.ndarray:
    """Block-mean a strip whose row count is a multiple of *k* (extra columns dropped)."""
    if k == 1:
        return strip[:, :out_w].astype(np.float32, copy=False)
    rows = strip.shape[0]
    blocks = strip[:, : out_w * k].reshape(rows // k, k, out_w, k)
    return blocks.mean(axis=(1, 3), dtype=np.float32)


def load_preview_base(fits_path: Path, max_dim: int = _PREVIEW_MAX_DIM) -> PreviewBase:
    """Stream *fits_path* in row strips into a binned ``PreviewBase``.

    Blocking — call through asyncio.to_thread. Rows/columns beyond the last whole
    k×k block (at most k − 1 of each) are left out of the binned image but still
    counted in the histogram and mean.
    """
    with fits.open(fits_path, memmap=True, do_not_scale_image_data=True) as hdul:
        hdu = hdul[0]
        raw = hdu.data  # type: ignore[union-attr]
        if raw is None:
            raise ValueError(f"No image data in FITS file: {fits_path}")
        if raw.ndim != 2:
            raise ValueError(f"Expected a 2-D image in {fits_path}, got shape {raw.shape}")
        bzero = float(hdu.header.get("BZERO", 0.0))  # type: ignore[union-attr]
        bscale = float(hdu.header.get("BSCALE", 1.0))  # type: ignore[union-attr]
        # float32 is exact for 16-bit integers; wider types need float64 to stay exact.
        work_dtype = np.float64 if raw.dtype.itemsize >= 4 else np.float32

        height, width = raw.shape
        pattern = _bayer_pattern(hdu.header) if height >= 2 and width >= 2 else None  # type: ignore[arg-type]
        k = _bin_factor(height, width, max_dim, bayer=pattern is not None)
        out_h, out_w = height // k, width // k
        rows_per_strip = max(k, (_STRIP_PIXELS // max(width, 1)) // k * k)

        def strips():
            for start in range(0, height, rows_per_strip):
                yield start, _physical(raw[start:start + rows_per_strip], bzero, bscale, work_dtype)

        adu_max = _adu_max(raw, bzero, bscale)
        fixed_scale = adu_max is not None
        if adu_max is None:
            # No fixed full scale — needs the data's own max before the histogram
            # range is known, hence a separate (cheap, memory-mapped) pass.
            adu_max = max(float(s.max()) for _, s in strips())
        hist_max = adu_max if adu_max > 0 else 1.0

        # Odd strides so the sample hits all four sites of a Bayer pattern.
        step = max(1, math.isqrt(height * width // _SAMPLE_TARGET)) | 1
        sat_threshold = adu_max * _SATURATION_FRACTION if fixed_scale else None

        binned = np.empty((out_h, out_w, 3) if pattern else (out_h, out_w), dtype=np.float32)
        histogram = np.zeros(_HIST_BINS, dtype=np.int64)
        channel_hists = np.zeros((3, _HIST_BINS), dtype=np.int64)
        samples: list[np.ndarray] = []
        channel_samples: list[list[np.ndarray]] = [[], [], []]
        # Per-site sampling stride (a site plane has a quarter of the pixels).
        site_step = max(1, math.isqrt(height * width // 4 // _SAMPLE_TARGET))
        saturated = 0
        total = 0.0
        for start, strip in strips():
            total += float(strip.sum(dtype=np.float64))
            if pattern:
                # Strips start on even rows (rows_per_strip is a multiple of even k).
                for i, colour in enumerate(pattern):
                    c = _CHANNEL_NAMES.index(colour)
                    site = strip[i // 2::2, i % 2::2]
                    channel_hists[c] += np.histogram(site, bins=_HIST_BINS, range=(0.0, hist_max))[0]
                    channel_samples[c].append(
                        site[(-(start // 2)) % site_step::site_step, ::site_step].astype(np.float32).ravel()
                    )
            else:
                histogram += np.histogram(strip, bins=_HIST_BINS, range=(0.0, hist_max))[0]
                samples.append(strip[(-start) % step::step, ::step].astype(np.float32).ravel())
            if sat_threshold is not None:
                saturated += int(np.count_nonzero(strip >= sat_threshold))
            # Only rows that complete a k-row block (a strip's row count is a multiple
            # of k except possibly the last one).
            usable = min(strip.shape[0], out_h * k - start) // k * k
            if usable > 0:
                rows = slice(start // k, (start + usable) // k)
                if pattern:
                    binned[rows] = _bin_bayer_rows(strip[:usable], k, out_w, pattern)
                else:
                    binned[rows] = _bin_rows(strip[:usable], k, out_w)

        per_channel: tuple[np.ndarray, ...] | None = None
        if pattern:
            histogram = channel_hists.sum(axis=0)
            per_channel = tuple(np.concatenate(cs) for cs in channel_samples)
            samples = list(per_channel)

    return PreviewBase(
        data=binned,
        adu_max=adu_max,
        histogram=histogram,
        hist_max=hist_max,
        mean=total / (height * width),
        full_sample=np.concatenate(samples),
        saturated=saturated if fixed_scale else None,
        width=width,
        height=height,
        bin_factor=k,
        bayer_pattern=pattern,
        channel_histograms=channel_hists if pattern else None,
        channel_samples=per_channel,
    )


class PreviewBaseCache:
    """Small thread-safe LRU of ``PreviewBase`` objects keyed by file identity.

    The key includes mtime and size, so a path that gets overwritten (e.g. the
    imager's per-camera temp FITS for unsaved frames) is never served stale.
    ``load`` is blocking — call it through asyncio.to_thread.
    """

    def __init__(self, capacity: int = 2) -> None:
        self._capacity = capacity
        self._items: "OrderedDict[tuple, PreviewBase]" = OrderedDict()
        self._lock = threading.Lock()

    def load(self, fits_path: Path, max_dim: int = _PREVIEW_MAX_DIM) -> PreviewBase:
        st = Path(fits_path).stat()
        key = (str(Path(fits_path).resolve()), st.st_mtime_ns, st.st_size, max_dim)
        with self._lock:
            base = self._items.get(key)
            if base is not None:
                self._items.move_to_end(key)
                return base
        base = load_preview_base(fits_path, max_dim)
        with self._lock:
            self._items[key] = base
            self._items.move_to_end(key)
            while len(self._items) > self._capacity:
                self._items.popitem(last=False)
        return base


def _mtf_to_uint8(data: np.ndarray, low: float, high: float, m: float, adu_max: float) -> np.ndarray:
    """Clip *data* to [low, high], rescale to [0, 1], apply ``mtf(m, ·)``, → uint8.

    m = 0.5 is the identity curve (a plain linear clip).

    When low == high a *relative* stretch is undefined: (data - low) is 0
    everywhere regardless of how bright that level actually was, which used to
    render a fully saturated frame pitch black instead of white. Fall back to
    the level's own position in the sensor's full-scale range instead.

    Never modifies *data* (it may be a cached base); works on one float copy.
    """
    span = high - low
    if span < 1e-8:
        level = float(np.clip(low / adu_max, 0.0, 1.0)) if adu_max > 0 else 0.0
        return np.full(data.shape, round(level * 255), dtype=np.uint8)
    x = data - np.float32(low)
    x *= np.float32(1.0 / span)
    np.clip(x, 0.0, 1.0, out=x)
    if abs(m - 0.5) > 1e-6:
        # MTF(m, x) = (m − 1)·x / ((2m − 1)·x − m); the denominator is < 0 on [0, 1].
        den = x * np.float32(2 * m - 1)
        den -= np.float32(m)
        x *= np.float32(m - 1)
        x /= den
    x *= np.float32(255.0)
    return x.astype(np.uint8)


def _save_jpeg(uint8_data: np.ndarray, jpeg_path: Path, quality: int) -> None:
    mode = "RGB" if uint8_data.ndim == 3 else "L"
    Image.fromarray(uint8_data, mode=mode).save(jpeg_path, format="JPEG", quality=quality)


def mtf(m: float, x: float) -> float:
    """Midtones transfer function: maps 0 → 0, m → 0.5, 1 → 1."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    return (m - 1) * x / ((2 * m - 1) * x - m)


def _robust_sigma(sample: np.ndarray, median: float) -> float:
    return _MAD_TO_SIGMA * float(np.median(np.abs(sample - np.float32(median))))


def _stretch_from_sample(
    sample: np.ndarray, adu_max: float, target_bg: float, shadows_sigma: float,
) -> tuple[float, float, float]:
    median = float(np.median(sample))
    sigma = _robust_sigma(sample, median)
    white = adu_max
    if sigma <= 0.0 or white <= 0.0:
        return 0.0, white, 0.5
    black = min(max(median + shadows_sigma * sigma, 0.0), white)
    span = white - black
    if span <= 0.0:
        return black, white, 0.5
    x0 = (median - black) / span  # background after rescaling to [0, 1]
    if x0 <= 0.0 or x0 >= target_bg:
        return black, white, 0.5
    # Solving MTF(m, x0) = target_bg for m gives m = MTF(target_bg, x0).
    return black, white, mtf(target_bg, x0)


def auto_stretch_params(
    base: PreviewBase,
    target_bg: float = DEFAULT_TARGET_BG,
    shadows_sigma: float = DEFAULT_SHADOWS_SIGMA,
    channel: int | None = None,
) -> tuple[float, float, float]:
    """(black point ADU, white point ADU, midtones balance m) for the auto stretch.

    For one channel of a colour base, or its luminance when *channel* is None.
    Statistics come from the binned base — the noise level actually visible in the
    preview — so a setting looks the same whatever the sensor size or bin factor.

    Edge cases:
    - no measurable noise (a flat frame: bias-free synthetic data, a fully saturated
      or black frame) → plain linear [0, full scale] view, so a saturated frame
      renders white and a black one black;
    - background already at or above the target (twilight flats) → no midtone boost.
    """
    return _stretch_from_sample(base.sample(channel), base.adu_max, target_bg, shadows_sigma)


def _describe(sample: np.ndarray) -> tuple[float, float]:
    median = float(np.median(sample))
    return median, _robust_sigma(sample, median)


def auto_stretch_stats(
    base: PreviewBase,
    target_bg: float = DEFAULT_TARGET_BG,
    shadows_sigma: float = DEFAULT_SHADOWS_SIGMA,
    linked: bool = False,
) -> dict:
    """Stats dict (histogram + stretch parameters) for an ``ImageStats``.

    The histogram is binned over the sensor's full-scale range (not the frame's own
    min/max) so clipped highlights show as a spike at the true right edge and the
    shot's exposure level can be judged at a glance, instead of the axis silently
    rescaling to whatever this particular frame's brightest/darkest pixel was. It is
    computed at full resolution, so binning can't average a clipping spike away.

    ``median``/``noise_sigma``/``saturated_pct`` describe the full-resolution frame
    (what an exposure decision needs); ``display_median``/``display_sigma`` describe
    the binned base the stretch is computed on (its luminance, for colour), so a
    client can recompute the stretch curve for other parameters without a round trip.

    For a colour base, ``channels`` repeats this per R/G/B channel; each channel's
    stretch is its own (unlinked) or the luminance one (*linked*).
    """
    lum_params = auto_stretch_params(base, target_bg, shadows_sigma)
    median, noise_sigma = _describe(base.full_sample)
    display_median, display_sigma = _describe(base.sample())
    total_pixels = base.width * base.height

    channels = None
    if base.is_color and base.channel_histograms is not None and base.channel_samples is not None:
        channels = []
        for c, name in enumerate(_CHANNEL_NAMES):
            c_display = base.sample(c)
            c_median, c_sigma = _describe(base.channel_samples[c])
            c_display_median, c_display_sigma = _describe(c_display)
            low, high, m = lum_params if linked else _stretch_from_sample(
                c_display, base.adu_max, target_bg, shadows_sigma,
            )
            channels.append({
                "name": name,
                "histogram": base.channel_histograms[c].tolist(),
                "median": c_median,
                "noise_sigma": c_sigma,
                "display_median": c_display_median,
                "display_sigma": c_display_sigma,
                "stretch_low": low,
                "stretch_high": high,
                "stretch_midtone": m,
            })

    if channels:
        # A mixed-CFA sample's MAD is inflated by the offsets between channel
        # backgrounds — report the typical per-channel noise instead.
        noise_sigma = float(np.mean([ch["noise_sigma"] for ch in channels]))

    black, white, m = lum_params
    return {
        "histogram": base.histogram.tolist(),
        "hist_min": 0.0,
        "hist_max": base.hist_max,
        "stretch_low": black,
        "stretch_high": white,
        "stretch_midtone": m,
        "mean": base.mean,
        "median": median,
        "noise_sigma": noise_sigma,
        "saturated_pct": (
            100.0 * base.saturated / total_pixels if base.saturated is not None and total_pixels else None
        ),
        "display_median": display_median,
        "display_sigma": display_sigma,
        "channels": channels,
    }


def render_auto(
    base: PreviewBase,
    jpeg_path: Path,
    quality: int = 85,
    target_bg: float = DEFAULT_TARGET_BG,
    shadows_sigma: float = DEFAULT_SHADOWS_SIGMA,
    *,
    color: bool = True,
    linked: bool = False,
) -> dict:
    """Auto-stretch *base* to a JPEG; returns the ``auto_stretch_stats`` dict.

    A colour base renders as RGB unless *color* is False (luminance instead).
    """
    stats = auto_stretch_stats(base, target_bg, shadows_sigma, linked)
    if base.is_color and color and stats["channels"]:
        rgb = np.empty(base.data.shape, dtype=np.uint8)
        for c, ch in enumerate(stats["channels"]):
            rgb[..., c] = _mtf_to_uint8(
                base.data[..., c], ch["stretch_low"], ch["stretch_high"], ch["stretch_midtone"], base.adu_max,
            )
        _save_jpeg(rgb, jpeg_path, quality)
    else:
        _save_jpeg(
            _mtf_to_uint8(
                base.luminance(), stats["stretch_low"], stats["stretch_high"], stats["stretch_midtone"],
                base.adu_max,
            ),
            jpeg_path, quality,
        )
    return stats


def render_linear(base: PreviewBase, jpeg_path: Path, quality: int = 85, *, color: bool = True) -> None:
    """Linear: map [0, sensor full-scale ADU] to [0, 255], same scale for every frame.

    Deliberately *not* a per-frame min/max stretch — that would independently
    renormalise each frame's own narrow range to fill [0, 255], making two frames
    with genuinely different brightness (e.g. two flats at different exposures)
    render identically. Anchoring to the sensor's fixed full-scale ADU instead
    keeps brightness comparable across frames, at the cost of a dim frame simply
    looking dim (as it should for a "linear, unstretched" view).
    """
    data = base.data if color else base.luminance()
    _save_jpeg(_mtf_to_uint8(data, 0.0, base.adu_max, 0.5, base.adu_max), jpeg_path, quality)


def fits_to_jpeg(
    fits_path: Path,
    jpeg_path: Path,
    quality: int = 85,
    target_bg: float = DEFAULT_TARGET_BG,
    shadows_sigma: float = DEFAULT_SHADOWS_SIGMA,
) -> dict:
    """Auto-stretch a FITS file to a JPEG (convenience wrapper, no caching)."""
    return render_auto(load_preview_base(fits_path), jpeg_path, quality, target_bg, shadows_sigma)


def fits_to_jpeg_linear(fits_path: Path, jpeg_path: Path, quality: int = 85) -> None:
    """Linear-stretch a FITS file to a JPEG (convenience wrapper, no caching)."""
    render_linear(load_preview_base(fits_path), jpeg_path, quality)


def fits_to_thumbnail(fits_path: Path, jpeg_path: Path, max_dim: int = 256, quality: int = 70) -> None:
    """Small, fixed-stretch preview for a library grid/list — never re-adjustable.

    Uses the same default auto-stretch as ``fits_to_jpeg`` but
    binned straight down to thumbnail size, so generating thousands of these (an
    imported library) is cheap relative to full-resolution previews.
    """
    render_auto(load_preview_base(fits_path, max_dim=max_dim), jpeg_path, quality)
