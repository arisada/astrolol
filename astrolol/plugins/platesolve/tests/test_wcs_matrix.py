"""The solve result carries the WCS matrix, which says whether the image is mirrored."""
from __future__ import annotations

import astropy.io.fits as fits
import numpy as np

from astrolol.plugins.platesolve.solver import _parse_wcs


def _solved_file(path, cd) -> str:
    hdu = fits.PrimaryHDU(np.zeros((20, 30), dtype=np.float32))
    hdu.header.update({"CRVAL1": 83.8, "CRVAL2": -5.4})
    for key, value in zip(("CD1_1", "CD1_2", "CD2_1", "CD2_2"), cd):
        hdu.header[key] = value
    hdu.writeto(path)
    return str(path)


def test_matrix_is_returned(tmp_path) -> None:
    cd = (-5e-4, 1e-5, 1e-5, 5e-4)
    result = _parse_wcs(_solved_file(tmp_path / "a.fits", cd))
    assert result.cd == cd


def test_mirroring_shows_in_the_matrix(tmp_path) -> None:
    normal = _parse_wcs(_solved_file(tmp_path / "n.fits", (-5e-4, 0.0, 0.0, 5e-4)))
    mirrored = _parse_wcs(_solved_file(tmp_path / "m.fits", (5e-4, 0.0, 0.0, 5e-4)))
    det = lambda r: r.cd[0] * r.cd[3] - r.cd[1] * r.cd[2]
    assert det(normal) < 0 < det(mirrored)
