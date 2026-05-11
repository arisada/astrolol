"""Ephemeris computations for the target plugin.

Uses astroplan (which wraps astropy) to compute rise/set/transit times,
altitude curves, twilight boundaries, and moon data for a fixed sky target.

All returned times are UTC ISO strings.  The caller supplies the observer
location (lat/lon/alt) and the observation date (a Python date or datetime);
the computation window is noon-to-noon local time centred on that date.
"""
from __future__ import annotations

import math
import warnings
from datetime import date, datetime, timedelta, timezone

import numpy as np
import structlog
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body
from astropy.time import Time
from astroplan import FixedTarget, Observer

from plugins.target.models import AltitudePoint, EphemerisResult, TwilightTimes

logger = structlog.get_logger()

_CURVE_STEP_MINUTES = 10   # resolution of the altitude curve
_WINDOW_HOURS = 24         # total window to compute


def _to_utc_iso(t: Time) -> str:
    return t.to_datetime(timezone.utc).isoformat()


def _midnight_utc(obs_date: date, observer: Observer) -> Time:
    """Return UTC time of solar midnight for the night *starting* on obs_date.

    obs_date is the calendar date of the evening (dusk side).  Solar midnight
    falls on obs_date+1 in solar time, so we compute midnight of the next
    calendar day shifted by the longitude-based UTC offset.
    """
    next_day = obs_date + timedelta(days=1)
    naive_midnight = datetime(next_day.year, next_day.month, next_day.day, 0, 0, 0)
    lon_deg = observer.location.lon.deg  # type: ignore[union-attr]
    utc_offset_hours = lon_deg / 15.0
    utc_midnight = naive_midnight - timedelta(hours=utc_offset_hours)
    return Time(utc_midnight.replace(tzinfo=timezone.utc))


def compute_ephemeris(
    ra_deg: float,
    dec_deg: float,
    latitude: float,
    longitude: float,
    altitude_m: float,
    obs_date: date | None = None,
    min_altitude_deg: float = 30.0,
) -> EphemerisResult:
    """Compute rise/set/transit, altitude curve, twilight, and moon data.

    Args:
        ra_deg: ICRS right ascension in degrees.
        dec_deg: ICRS declination in degrees.
        latitude: Observer latitude in degrees (positive = North).
        longitude: Observer longitude in degrees (positive = East).
        altitude_m: Observer altitude in metres above sea level.
        obs_date: Observation date (local).  Defaults to today UTC.
        min_altitude_deg: Minimum useful altitude for imaging window calculation.

    Returns:
        EphemerisResult with all fields populated.
    """
    now_utc: datetime | None = None
    if obs_date is None:
        now_utc = datetime.now(timezone.utc)
        obs_date = now_utc.date()

    location = EarthLocation(
        lat=latitude * u.deg,
        lon=longitude * u.deg,
        height=altitude_m * u.m,
    )
    logger.debug("target.ephemeris", latitude=latitude, longitude=longitude, altitude_m=altitude_m, obs_date=str(obs_date))
    observer = Observer(location=location)
    target = FixedTarget(SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs"))

    # Centre the window on solar midnight for the night starting on obs_date.
    # When no explicit date was supplied, snap to the correct night:
    #   now > window_end   → night is over, advance to tomorrow
    #   now < window_start → early morning, still inside last night
    t_midnight = _midnight_utc(obs_date, observer)
    if now_utc is not None:
        t_window_start = (t_midnight - timedelta(hours=_WINDOW_HOURS / 2)).to_datetime(timezone.utc)
        t_window_end   = (t_midnight + timedelta(hours=_WINDOW_HOURS / 2)).to_datetime(timezone.utc)
        if now_utc > t_window_end:
            obs_date   = obs_date + timedelta(days=1)
            t_midnight = _midnight_utc(obs_date, observer)
        elif now_utc < t_window_start:
            obs_date   = obs_date - timedelta(days=1)
            t_midnight = _midnight_utc(obs_date, observer)

    t_start = t_midnight - timedelta(hours=_WINDOW_HOURS / 2)
    t_end   = t_midnight + timedelta(hours=_WINDOW_HOURS / 2)

    # ── Rise / transit / set ──────────────────────────────────────────────────
    # Compute the full altitude curve first so we can derive peak from it
    # reliably regardless of astroplan's transit-time numerical edge cases.
    rise: str | None = None
    transit: str | None = None
    t_set: str | None = None
    circumpolar = False
    never_rises = False
    peak_alt: float | None = None
    peak_time: str | None = None

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            t_rise = observer.target_rise_time(t_midnight, target, which="nearest",
                                               horizon=0 * u.deg)
            if not math.isnan(t_rise.jd):
                rise = _to_utc_iso(t_rise)
        except Exception:
            pass

        try:
            t_set_time = observer.target_set_time(t_midnight, target, which="nearest",
                                                  horizon=0 * u.deg)
            if not math.isnan(t_set_time.jd):
                t_set = _to_utc_iso(t_set_time)
        except Exception:
            pass

    # Circumpolar / never-rises detection: if max altitude is always above or
    # always below the horizon, rise/set calls return NaN.
    if rise is None and t_set is None:
        # sample a few altitudes to distinguish the two cases
        sample_times = t_start + np.linspace(0, _WINDOW_HOURS * 3600, 24) * u.s
        alts = observer.altaz(Time(sample_times), target).alt.deg
        if np.max(alts) < 1.0:
            never_rises = True
        else:
            circumpolar = True

    # ── Altitude curve ────────────────────────────────────────────────────────
    n_steps = int(_WINDOW_HOURS * 60 / _CURVE_STEP_MINUTES) + 1
    offsets = np.linspace(0, _WINDOW_HOURS * 3600, n_steps) * u.s
    times = Time(t_start) + offsets
    altaz_frame = AltAz(obstime=times, location=location)
    sky_coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")
    alts_arr = sky_coord.transform_to(altaz_frame).alt.deg

    altitude_curve: list[AltitudePoint] = []
    for i, t in enumerate(times):
        altitude_curve.append(AltitudePoint(
            time=_to_utc_iso(t),
            alt=float(alts_arr[i]),
        ))

    # Peak altitude from the curve (reliable, 10-min resolution)
    peak_idx = int(np.argmax(alts_arr))
    peak_alt = float(alts_arr[peak_idx])
    peak_time = _to_utc_iso(times[peak_idx])

    # Try to refine transit time with astroplan (higher precision)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            t_transit_ap = observer.target_transit_time(t_midnight, target, which="nearest")
            if not math.isnan(t_transit_ap.jd):
                transit = _to_utc_iso(t_transit_ap)
                alt_at_transit = float(observer.altaz(t_transit_ap, target).alt.deg)
                # Only override curve-derived peak if astroplan value is plausible
                if abs(alt_at_transit - peak_alt) < 5.0:
                    peak_alt = alt_at_transit
                    peak_time = transit
        except Exception:
            pass

    # ── Twilight (computed before imaging window so dark period is available) ──
    def _twilight(horizon_deg: float, which: str) -> str | None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                if which == "dusk":
                    t = observer.sun_set_time(t_midnight, which="previous",
                                              horizon=horizon_deg * u.deg)
                else:
                    t = observer.sun_rise_time(t_midnight, which="next",
                                               horizon=horizon_deg * u.deg)
                return None if math.isnan(t.jd) else _to_utc_iso(t)
            except Exception:
                return None

    twilight = TwilightTimes(
        civil_dusk=_twilight(-6.0, "dusk"),
        nautical_dusk=_twilight(-12.0, "dusk"),
        astronomical_dusk=_twilight(-18.0, "dusk"),
        civil_dawn=_twilight(-6.0, "dawn"),
        nautical_dawn=_twilight(-12.0, "dawn"),
        astronomical_dawn=_twilight(-18.0, "dawn"),
    )

    # ── Imaging window: altitude above threshold AND within dark period ────────
    # Use nautical twilight as the dark boundary (good enough for imaging);
    # fall back to civil if nautical doesn't occur (high-latitude short nights).
    dark_start_iso = twilight.nautical_dusk or twilight.civil_dusk
    dark_end_iso   = twilight.nautical_dawn or twilight.civil_dawn

    imaging_window_start: str | None = None
    imaging_window_end: str | None = None
    not_observable_at_night = False

    above = alts_arr >= min_altitude_deg

    if dark_start_iso and dark_end_iso:
        t_dark_start = Time(datetime.fromisoformat(dark_start_iso))
        t_dark_end   = Time(datetime.fromisoformat(dark_end_iso))
        dark = (times.jd >= t_dark_start.jd) & (times.jd <= t_dark_end.jd)
        usable = above & dark

        # Find first contiguous usable block
        for i in range(len(usable) - 1):
            if not usable[i] and usable[i + 1]:
                imaging_window_start = _to_utc_iso(times[i + 1])
                break
            elif usable[i] and i == 0:
                imaging_window_start = _to_utc_iso(times[0])
                break

        if imaging_window_start is not None:
            started = False
            for i in range(len(times)):
                if usable[i]:
                    started = True
                elif started:
                    imaging_window_end = _to_utc_iso(times[i])
                    break
            if started and imaging_window_end is None:
                imaging_window_end = _to_utc_iso(times[-1])
        else:
            # Object is up at some point (not never_rises) but not high enough during darkness
            if not never_rises:
                not_observable_at_night = True
    else:
        # No usable dark period (midnight-sun conditions) — fall back to altitude only
        for i in range(len(above) - 1):
            if not above[i] and above[i + 1]:
                imaging_window_start = _to_utc_iso(times[i + 1])
                break
            elif above[i] and i == 0:
                imaging_window_start = _to_utc_iso(times[0])
                break
        if imaging_window_start is not None:
            started = False
            for i in range(len(times)):
                if above[i]:
                    started = True
                elif started:
                    imaging_window_end = _to_utc_iso(times[i])
                    break
            if started and imaging_window_end is None:
                imaging_window_end = _to_utc_iso(times[-1])

    # ── Moon ──────────────────────────────────────────────────────────────────
    # Use the midpoint of the darkest available twilight band as the reference
    # time for illumination and separation — t_midnight is solar midnight which
    # can be hours away from when the moon actually matters for imaging.
    t_moon_ref = t_midnight
    _tw_pairs = [
        (twilight.astronomical_dusk, twilight.astronomical_dawn),
        (twilight.nautical_dusk, twilight.nautical_dawn),
        (twilight.civil_dusk, twilight.civil_dawn),
    ]
    for _dusk_iso, _dawn_iso in _tw_pairs:
        if _dusk_iso and _dawn_iso:
            _t1 = Time(datetime.fromisoformat(_dusk_iso))
            _t2 = Time(datetime.fromisoformat(_dawn_iso))
            t_moon_ref = Time((_t1.jd + _t2.jd) / 2, format='jd')
            break

    moon_separation: float | None = None
    moon_illumination: float | None = None
    moon_altitude_curve: list[AltitudePoint] = []
    try:
        moon_coord = get_body("moon", t_moon_ref, location=location)
        # Convert GCRS → ICRS before separation to avoid the NonRotationTransformationWarning
        moon_icrs = SkyCoord(ra=moon_coord.icrs.ra, dec=moon_coord.icrs.dec, frame="icrs")
        target_coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")
        moon_separation = float(target_coord.separation(moon_icrs).deg)
        moon_illumination = float(observer.moon_illumination(t_moon_ref))

        # Full altitude curve for the moon over the same time window
        moon_coords_all = get_body("moon", times, location=location)
        moon_altaz_all = moon_coords_all.transform_to(AltAz(obstime=times, location=location))
        moon_alts_arr = moon_altaz_all.alt.deg
        for i, t in enumerate(times):
            moon_altitude_curve.append(AltitudePoint(
                time=_to_utc_iso(t),
                alt=float(moon_alts_arr[i]),
            ))
    except Exception:
        pass

    return EphemerisResult(
        obs_date=obs_date.isoformat(),
        rise=rise,
        transit=transit,
        set=t_set,
        circumpolar=circumpolar,
        never_rises=never_rises,
        peak_alt=peak_alt,
        peak_time=peak_time,
        imaging_window_start=imaging_window_start,
        imaging_window_end=imaging_window_end,
        not_observable_at_night=not_observable_at_night,
        altitude_curve=altitude_curve,
        twilight=twilight,
        moon_separation=moon_separation,
        moon_illumination=moon_illumination,
        moon_altitude_curve=moon_altitude_curve,
    )
