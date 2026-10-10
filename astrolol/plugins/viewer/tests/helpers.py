"""Shared helpers for viewer plugin tests."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from astropy.io import fits


def write_fits(path: Path, data: np.ndarray | None = None, **header: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if data is None:
        data = np.full((32, 32), 1000, dtype=np.uint16)
    hdu = fits.PrimaryHDU(data.astype(np.uint16))
    for key, value in header.items():
        hdu.header[key] = value
    hdu.writeto(path, overwrite=True)
    return path
