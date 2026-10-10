from astrolol.plugins.viewer.coords import resolve_coords


def test_no_coordinates_resolves_to_none() -> None:
    ra, dec, source = resolve_coords({})
    assert (ra, dec, source) == (None, None, None)


def test_icrs_header_is_used_when_present() -> None:
    ra, dec, source = resolve_coords({"RA": 83.822, "DEC": -5.391})
    assert source == "header_icrs"
    assert ra == 83.822
    assert dec == -5.391


def test_invalid_icrs_header_is_ignored() -> None:
    ra, dec, source = resolve_coords({"RA": 999.0, "DEC": -5.0})
    assert (ra, dec, source) == (None, None, None)


def test_sexagesimal_objctra_objctdec_resolves_to_icrs() -> None:
    # M42 (Orion Nebula), roughly RA 05h35m17s Dec -05d23m28s (J2000).
    ra, dec, source = resolve_coords({
        "OBJCTRA": "05 35 17.3",
        "OBJCTDEC": "-05 23 28",
        "EQUINOX": 2000.0,
    })
    assert source == "header_jnow"
    assert ra is not None and dec is not None
    assert abs(ra - 83.82) < 0.5
    assert abs(dec - (-5.39)) < 0.5


def test_wcs_takes_priority_over_plain_ra_dec_header() -> None:
    header = {
        "RA": 0.0, "DEC": 0.0,  # a deliberately different "reported" pointing
        "NAXIS1": 100, "NAXIS2": 100,
        "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
        "CRPIX1": 50.0, "CRPIX2": 50.0,
        "CRVAL1": 83.822, "CRVAL2": -5.391,
        "CDELT1": -0.001, "CDELT2": 0.001,
        "CUNIT1": "deg", "CUNIT2": "deg",
    }
    ra, dec, source = resolve_coords(header)
    assert source == "wcs"
    assert ra is not None and abs(ra - 83.822) < 0.01
    assert dec is not None and abs(dec - (-5.391)) < 0.01
