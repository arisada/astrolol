"""Header -> ICRS coordinate resolution for arbitrary (not necessarily astrolol-written)
FITS files.

Tried in priority order, since a plate-solved WCS is a measurement while any RA/DEC
header is only where a mount *reported* it was pointing:

1. WCS (``CRVAL1``/``CRVAL2`` + the rest of the WCS keywords) — the image-center sky
   position computed via ``pixel_to_world`` at (NAXIS1/2, NAXIS2/2), not just CRVAL taken
   literally (CRVAL is only the image center when CRPIX happens to be centered).
2. ``RA``/``DEC`` in ICRS degrees — astrolol's own header patch
   (see ``astrolol.imaging.imager._patch_fits_headers``).
3. ``OBJCTRA``/``OBJCTDEC`` sexagesimal strings with ``EQUINOX``, written by other
   capture tools — parsed as an equinox-of-date (JNow) frame and precessed to ICRS.
"""
from __future__ import annotations

CoordSource = str  # "wcs" | "header_icrs" | "header_jnow"


def resolve_coords(header: dict) -> tuple[float | None, float | None, CoordSource | None]:
    """Return (ra_deg, dec_deg, coord_source) in ICRS, or (None, None, None)."""
    coord = _from_wcs(header)
    if coord is not None:
        return coord[0], coord[1], "wcs"

    coord = _from_icrs_header(header)
    if coord is not None:
        return coord[0], coord[1], "header_icrs"

    coord = _from_sexagesimal_jnow(header)
    if coord is not None:
        return coord[0], coord[1], "header_jnow"

    return None, None, None


def _from_wcs(header: dict) -> tuple[float, float] | None:
    if "CRVAL1" not in header or "CRVAL2" not in header:
        return None
    try:
        from astropy.wcs import WCS

        wcs = WCS(header)
        if not wcs.has_celestial:
            return None
        naxis1 = float(header.get("NAXIS1", 0)) or 1.0
        naxis2 = float(header.get("NAXIS2", 0)) or 1.0
        sky = wcs.pixel_to_world(naxis1 / 2.0, naxis2 / 2.0)
        icrs = sky.icrs
        return float(icrs.ra.deg), float(icrs.dec.deg)
    except Exception:
        return None


def _from_icrs_header(header: dict) -> tuple[float, float] | None:
    if "RA" not in header or "DEC" not in header:
        return None
    try:
        ra = float(header["RA"])
        dec = float(header["DEC"])
        if not (0.0 <= ra <= 360.0 and -90.0 <= dec <= 90.0):
            return None
        return ra, dec
    except (TypeError, ValueError):
        return None


def _from_sexagesimal_jnow(header: dict) -> tuple[float, float] | None:
    if "OBJCTRA" not in header or "OBJCTDEC" not in header:
        return None
    try:
        import astropy.units as u
        from astropy.coordinates import FK5, SkyCoord
        from astropy.time import Time

        equinox_year = float(header.get("EQUINOX", 2000.0))
        frame = FK5(equinox=Time(equinox_year, format="jyear"))
        coord = SkyCoord(
            f"{header['OBJCTRA']} {header['OBJCTDEC']}",
            unit=(u.hourangle, u.deg),
            frame=frame,
        )
        icrs = coord.icrs
        return float(icrs.ra.deg), float(icrs.dec.deg)
    except Exception:
        return None
