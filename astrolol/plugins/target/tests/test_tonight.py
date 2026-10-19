"""Tests for the "what to watch tonight" list: the maths, the ranking and the route."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest
from astropy import units as u
from astropy.coordinates import EarthLocation, get_body
from fastapi.testclient import TestClient

from astrolol.equipment.models import SiteItem
from astrolol.plugins.object_resolver.service import ObjectMatch
from astrolol.plugins.target import tonight
from astrolol.plugins.target.models import TonightItem
from astrolol.plugins.target.tests.test_target_api import _LONDON, _make_app

_SYDNEY = SiteItem(name="Sydney", latitude=-33.87, longitude=151.21, altitude=20.0)
_ARCTIC = SiteItem(name="Arctic", latitude=65.0, longitude=25.0, altitude=10.0)
_NOON = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


def _item(name: str, alt_now: float, near_moon: bool = False) -> TonightItem:
    return TonightItem(name=name, ra=0.0, dec=0.0, alt_now=alt_now, peak_alt=alt_now,
                       peak_time="2026-10-18T22:00:00+00:00", near_moon=near_moon)


# --- the maths ---

def test_an_object_on_the_meridian_is_at_colatitude_minus_declination() -> None:
    alts = tonight.altitudes(np.array([100.0]), np.array([20.0]), np.array([100.0]), latitude=50.0)
    assert alts[0, 0] == pytest.approx(90 - 50 + 20)


def test_altitude_is_negative_when_the_object_is_below_the_horizon() -> None:
    alts = tonight.altitudes(np.array([0.0]), np.array([0.0]), np.array([180.0]), latitude=50.0)
    assert alts[0, 0] == pytest.approx(-40.0)


def test_separation() -> None:
    sep = tonight.separation_deg(np.array([0.0, 10.0]), np.array([0.0, 20.0]), 90.0, 0.0)
    assert sep[0] == pytest.approx(90.0)
    assert tonight.separation_deg(np.array([10.0]), np.array([20.0]), 10.0, 20.0)[0] == pytest.approx(0.0, abs=1e-6)


@pytest.mark.parametrize(("sep", "moon_alt", "illum", "expected"), [
    (10.0, 40.0, 0.9, True),      # bright Moon up and near
    (50.0, 40.0, 0.9, False),     # far enough
    (10.0, -5.0, 0.9, False),     # the Moon is down
    (10.0, 40.0, 0.05, False),    # a thin crescent
    (29.9, 10.0, 0.15, True),
    (30.0, 10.0, 0.5, False),
])
def test_too_close_to_the_moon(sep: float, moon_alt: float, illum: float, expected: bool) -> None:
    assert tonight.is_too_close_to_moon(sep, moon_alt, illum) is expected


def test_ranking_is_highest_first_with_moon_spoiled_objects_last() -> None:
    ranked = tonight.rank([_item("low", 35), _item("moon-high", 80, near_moon=True),
                           _item("high", 70), _item("moon-low", 40, near_moon=True), _item("not-up-yet", -5)])
    assert [i.name for i in ranked] == ["high", "low", "not-up-yet", "moon-high", "moon-low"]


# --- the dark window ---

def test_from_the_afternoon_the_window_starts_at_dusk_and_ends_before_dawn_the_day_after() -> None:
    w = tonight.find_dark_window(_NOON, _LONDON.latitude, _LONDON.longitude, 10.0)
    assert w is not None
    assert w.start > _NOON
    assert 6 * 3600 < (w.end - w.start).total_seconds() < 14 * 3600


def test_in_the_middle_of_the_night_the_window_starts_now() -> None:
    now = datetime(2026, 10, 18, 23, 0, tzinfo=timezone.utc)
    w = tonight.find_dark_window(now, _LONDON.latitude, _LONDON.longitude, 10.0)
    assert w is not None
    assert w.start == now
    assert w.end > now


def test_no_darkness_in_the_midnight_sun() -> None:
    june = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
    assert tonight.find_dark_window(june, _ARCTIC.latitude, _ARCTIC.longitude, 10.0) is None


# --- ranking real objects ---

_M31 = {"name": "M 31", "aliases": ["NGC 224"], "type": "Galaxy", "ra": 10.685, "dec": 41.269, "source": "catalog"}
_POLE = {"name": "Polaris", "aliases": [], "type": "Star", "ra": 37.95, "dec": 89.26, "source": "catalog"}
_SOUTH = {"name": "Far south", "aliases": [], "type": "Star", "ra": 100.0, "dec": -70.0, "source": "catalog"}


def _london_window():
    return tonight.find_dark_window(_NOON, _LONDON.latitude, _LONDON.longitude, 10.0)


def test_only_objects_that_get_above_the_minimum_are_listed() -> None:
    result = tonight.compute_tonight([_M31, _POLE, _SOUTH], _london_window(), _LONDON.latitude, _LONDON.longitude, 10.0)
    names = {i.name for i in result.items}
    assert names == {"M 31", "Polaris"}                      # never rises above 30° from London
    assert all(i.peak_alt >= 30.0 for i in result.items)


def test_items_carry_when_they_peak_and_how_high() -> None:
    result = tonight.compute_tonight([_M31], _london_window(), _LONDON.latitude, _LONDON.longitude, 10.0)
    m31 = result.items[0]
    assert m31.peak_alt == pytest.approx(90 - 51.5 + 41.269, abs=1.5)    # near its transit altitude
    assert m31.aliases == ["NGC 224"] and m31.type == "Galaxy"
    assert result.window_start and result.window_end and result.moon_illumination is not None


def test_a_higher_minimum_altitude_drops_objects() -> None:
    result = tonight.compute_tonight([_M31, _POLE], _london_window(), _LONDON.latitude, _LONDON.longitude, 10.0, 60.0)
    assert {i.name for i in result.items} == {"M 31"}        # Polaris sits at ~51° from London


def test_an_object_not_up_yet_has_a_rise_time_and_one_that_sets_has_a_set_time() -> None:
    w = _london_window()
    # Sample RAs round the clock and look at what the window does to them.
    rows = [dict(_M31, name=f"r{ra}", ra=float(ra), dec=20.0) for ra in range(0, 360, 20)]
    items = tonight.compute_tonight(rows, w, _LONDON.latitude, _LONDON.longitude, 10.0).items
    assert any(i.rise_time for i in items) and any(i.set_time for i in items)
    for i in items:
        assert (i.rise_time is not None) == (i.alt_now < 30.0)
        if i.rise_time:
            assert i.rise_time > w.start.isoformat()


def test_the_limit_keeps_the_highest() -> None:
    rows = [dict(_M31, name=f"r{ra}", ra=float(ra), dec=20.0) for ra in range(0, 360, 20)]
    full = tonight.compute_tonight(rows, _london_window(), _LONDON.latitude, _LONDON.longitude, 10.0).items
    cut = tonight.compute_tonight(rows, _london_window(), _LONDON.latitude, _LONDON.longitude, 10.0, limit=3).items
    assert [i.name for i in cut] == [i.name for i in full[:3]]


def test_nothing_to_rank() -> None:
    assert tonight.compute_tonight([], _london_window(), _LONDON.latitude, _LONDON.longitude, 10.0).items == []


def test_an_object_next_to_a_bright_moon_goes_to_the_bottom_whatever_its_altitude() -> None:
    now = datetime(2026, 10, 18, 6, 0, tzinfo=timezone.utc)            # first quarter: the Moon is lit
    where = (_SYDNEY.latitude, _SYDNEY.longitude, _SYDNEY.altitude)
    w = tonight.find_dark_window(now, *where)
    assert w is not None
    location = EarthLocation(lat=where[0] * u.deg, lon=where[1] * u.deg, height=where[2] * u.m)
    moon = get_body("moon", w.times[0], location=location)
    beside_moon = {"name": "Beside the Moon", "aliases": [], "type": "Star", "source": "catalog",
                   "ra": float(moon.ra.deg), "dec": float(moon.dec.deg)}
    pole = {"name": "South pole star", "aliases": [], "type": "Star", "source": "catalog", "ra": 0.0, "dec": -89.0}
    result = tonight.compute_tonight([beside_moon, pole], w, *where)
    by_name = {i.name: i for i in result.items}
    assert result.moon_illumination is not None and result.moon_illumination > 0.3
    assert by_name["Beside the Moon"].near_moon is True
    assert by_name["Beside the Moon"].alt_now > by_name["South pole star"].alt_now
    assert [i.name for i in result.items] == ["South pole star", "Beside the Moon"]


def test_the_moon_itself_is_never_flagged() -> None:
    now = datetime(2026, 10, 18, 6, 0, tzinfo=timezone.utc)
    where = (_SYDNEY.latitude, _SYDNEY.longitude, _SYDNEY.altitude)
    w = tonight.find_dark_window(now, *where)
    location = EarthLocation(lat=where[0] * u.deg, lon=where[1] * u.deg, height=where[2] * u.m)
    moon = get_body("moon", w.times[0], location=location)
    row = {"name": "Moon", "aliases": [], "type": "Solar System", "source": "solar_system",
           "ra": float(moon.ra.deg), "dec": float(moon.dec.deg)}
    item = tonight.compute_tonight([row], w, *where).items[0]
    assert item.near_moon is False and item.moon_separation is None


# --- the route ---

class _Resolver:
    def __init__(self, found: list[dict] | None = None) -> None:
        self.calls: list[tuple] = []
        self.found = found if found is not None else [_M31, _POLE, _SOUTH]

    def notable(self, groups, when=None, site=None):
        self.calls.append((groups, when, site))
        if groups and "comet" in groups:
            raise KeyError("comet")
        return [ObjectMatch(**r) for r in self.found]


def _client(site: SiteItem | None = _LONDON) -> tuple[TestClient, _Resolver]:
    app = _make_app(site=site)
    resolver = _Resolver()
    app.state.object_resolver = resolver
    return TestClient(app), resolver


def test_route_lists_what_is_up_tonight_highest_first() -> None:
    client, resolver = _client()
    resp = client.get("/plugins/target/tonight", params={"when": _NOON.isoformat()})
    assert resp.status_code == 200
    data = resp.json()
    assert [i["name"] for i in data["items"]] == sorted(
        [i["name"] for i in data["items"]], key=lambda n: -next(x["alt_now"] for x in data["items"] if x["name"] == n))
    assert {i["name"] for i in data["items"]} == {"M 31", "Polaris"}
    assert data["min_altitude_deg"] == 30.0
    groups, when, site = resolver.calls[0]
    assert groups is None and site == (_LONDON.latitude, _LONDON.longitude, _LONDON.altitude)
    assert when is not None                                    # planets are placed for the night's middle


def test_route_passes_the_kinds_asked_for() -> None:
    client, resolver = _client()
    client.get("/plugins/target/tonight", params={"types": "galaxy, double_star", "when": _NOON.isoformat()})
    assert resolver.calls[0][0] == ["galaxy", "double_star"]


def test_route_refuses_an_unknown_kind() -> None:
    client, _ = _client()
    resp = client.get("/plugins/target/tonight", params={"types": "comet", "when": _NOON.isoformat()})
    assert resp.status_code == 422 and "comet" in resp.json()["detail"]


def test_route_without_a_site() -> None:
    client, _ = _client(site=None)
    data = client.get("/plugins/target/tonight").json()
    assert data["observer_location_missing"] is True and data["items"] == []


def test_route_without_darkness() -> None:
    client, _ = _client(site=_ARCTIC)
    data = client.get("/plugins/target/tonight", params={"when": "2026-06-21T12:00:00+00:00"}).json()
    assert data["no_darkness"] is True and data["items"] == []


def test_route_needs_the_object_resolver() -> None:
    app = _make_app(site=_LONDON)
    resp = TestClient(app).get("/plugins/target/tonight", params={"when": _NOON.isoformat()})
    assert resp.status_code == 503


def test_route_refuses_a_bad_date() -> None:
    client, _ = _client()
    assert client.get("/plugins/target/tonight", params={"when": "tomorrow"}).status_code == 422
