"""Thumbnail generation + on-disk cache.

Generating a thumbnail from raw FITS pixel data means decoding the full array — cheap for
one frame, but roughly 1-2s per 50MB frame on a Pi, so hours for a freshly-imported
20k-frame library if done eagerly. Two paths, both cheaper than that:

- **Live captures**: don't re-read the FITS at all — downscale the JPEG preview the core
  imager already generated (a fast Pillow resize).
- **Everything else** (a rescanned/imported frame with no existing preview JPEG):
  generated lazily, on first request only — never eagerly during a scan.

Filenames embed (size, mtime), so a file replaced at the same path invalidates its cached
thumbnail automatically without any explicit invalidation step.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from PIL import Image

THUMB_MAX_DIM = 256
THUMB_QUALITY = 70


def thumbnail_path(cache_dir: Path, image_id: str, size_bytes: int, mtime: float) -> Path:
    return cache_dir / f"{image_id}_{size_bytes}_{int(mtime)}.jpg"


async def ensure_thumbnail(
    cache_dir: Path, image_id: str, size_bytes: int, mtime: float, fits_path: Path,
    *, source_preview_jpeg: Path | None = None,
) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = thumbnail_path(cache_dir, image_id, size_bytes, mtime)
    if out.exists():
        return out
    if source_preview_jpeg is not None and source_preview_jpeg.exists():
        await asyncio.to_thread(_downscale_jpeg, source_preview_jpeg, out)
    else:
        from astrolol.imaging.preview import fits_to_thumbnail
        await asyncio.to_thread(fits_to_thumbnail, fits_path, out, THUMB_MAX_DIM, THUMB_QUALITY)
    return out


def _downscale_jpeg(src: Path, dst: Path) -> None:
    with Image.open(src) as img:
        img = img.convert("L")
        img.thumbnail((THUMB_MAX_DIM, THUMB_MAX_DIM), Image.LANCZOS)
        img.save(dst, format="JPEG", quality=THUMB_QUALITY)


def gc(cache_dir: Path, live_ids: set[str]) -> int:
    """Remove cached thumbnails whose image id is no longer in the index — called after
    library_dir changes or files are rejected/deleted."""
    if not cache_dir.exists():
        return 0
    removed = 0
    for f in cache_dir.iterdir():
        image_id = f.name.split("_", 1)[0]
        if image_id not in live_ids:
            f.unlink(missing_ok=True)
            removed += 1
    return removed
