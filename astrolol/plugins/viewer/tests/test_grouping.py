from astrolol.plugins.viewer.grouping import (
    compute_group_key,
    compute_night,
    round_exposure,
    round_gain,
    sky_cell,
)
from datetime import datetime, timezone


def _key(**overrides) -> str:
    base = dict(
        frame_type="light", object_name="M42", filter_name="Ha", camera_name="cam1",
        exposure_s=300.0, binning=1, gain=100, night="2026-09-29",
        sky_cell_ra=None, sky_cell_dec=None,
    )
    base.update(overrides)
    return compute_group_key(**base)


def test_lights_group_by_full_tuple() -> None:
    assert _key() == _key()
    assert _key(exposure_s=60.0) != _key(exposure_s=300.0)


def test_flats_ignore_exposure() -> None:
    # Auto-exposure sky flats vary their exposure frame to frame — must not split the group.
    a = _key(frame_type="flat", exposure_s=1.2)
    b = _key(frame_type="flat", exposure_s=3.4)
    assert a == b


def test_bias_keeps_gain_but_ignores_exposure() -> None:
    same_gain_diff_exposure = _key(frame_type="bias", exposure_s=0.001) == _key(frame_type="bias", exposure_s=0.002)
    diff_gain = _key(frame_type="bias", gain=100) != _key(frame_type="bias", gain=200)
    assert same_gain_diff_exposure
    assert diff_gain


def test_darks_ignore_night_but_keep_exposure_and_gain() -> None:
    same_night_irrelevant = _key(frame_type="dark", night="2026-01-01") == _key(frame_type="dark", night="2026-09-29")
    diff_exposure_splits = _key(frame_type="dark", exposure_s=60.0) != _key(frame_type="dark", exposure_s=120.0)
    assert same_night_irrelevant
    assert diff_exposure_splits


def test_blank_object_name_falls_back_to_sky_cell() -> None:
    a = _key(object_name="", sky_cell_ra=10.0, sky_cell_dec=20.0)
    b = _key(object_name="", sky_cell_ra=10.0, sky_cell_dec=20.0)
    c = _key(object_name="", sky_cell_ra=50.0, sky_cell_dec=60.0)
    assert a == b
    assert a != c


def test_two_distinct_untracked_targets_same_night_dont_merge() -> None:
    """The bug this fallback exists to fix: two different unnamed pointings shot the
    same night at the same settings must not collapse into one group."""
    cell_a = sky_cell(10.0, 20.0)
    cell_b = sky_cell(80.0, 20.0)
    assert cell_a != cell_b
    a = _key(object_name="", sky_cell_dec=cell_a[0], sky_cell_ra=cell_a[1])
    b = _key(object_name="", sky_cell_dec=cell_b[0], sky_cell_ra=cell_b[1])
    assert a != b


def test_round_exposure_and_gain_absorb_float_drift() -> None:
    assert round_exposure(300.00001) == round_exposure(300.0)
    assert round_gain(100.4) == round_gain(99.6) == 100


def test_night_bucket_crosses_local_midnight() -> None:
    before_midnight = datetime(2026, 9, 29, 23, 0, tzinfo=timezone.utc)
    after_midnight = datetime(2026, 9, 30, 1, 0, tzinfo=timezone.utc)
    # No SITELONG: falls back to system tz, but both timestamps are well within the
    # same noon-to-noon UTC-based window regardless of local offset within a few hours.
    night_before = compute_night(before_midnight, sitelong_deg=0.0)
    night_after = compute_night(after_midnight, sitelong_deg=0.0)
    assert night_before == night_after == "2026-09-29"
