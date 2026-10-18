"""Solar system positions must be where the body is in our sky (geocentric), not barycentric."""
from __future__ import annotations

from datetime import datetime, timezone

from astrolol.plugins.object_resolver import solar_system
from astrolol.plugins.object_resolver.solar_system import _angular_sep_deg


def _pos(name: str, when: datetime) -> tuple[float, float]:
    hit = solar_system.search(name, when=when)[0]
    return hit["ra"], hit["dec"]


def test_sun_is_at_the_equinox_point_in_march() -> None:
    ra, dec = _pos("sun", datetime(2026, 3, 20, 14, 46, tzinfo=timezone.utc))
    assert min(ra, 360 - ra) < 1.0 and abs(dec) < 0.5


def test_moon_is_opposite_the_sun_at_full_moon() -> None:
    when = datetime(2026, 10, 26, 4, 12, tzinfo=timezone.utc)
    sun, moon = _pos("sun", when), _pos("moon", when)
    assert _angular_sep_deg(*sun, *moon) > 170.0


def test_moon_is_next_to_the_sun_at_new_moon() -> None:
    when = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)  # around new moon
    sun, moon = _pos("sun", when), _pos("moon", when)
    assert _angular_sep_deg(*sun, *moon) < 10.0


def test_cone_search_finds_the_moon_at_its_search_position() -> None:
    when = datetime(2026, 10, 26, 4, 12, tzinfo=timezone.utc)
    ra, dec = _pos("moon", when)
    hits = solar_system.cone_search(ra, dec, 10.0, when=when)
    assert hits and hits[0]["name"] == "Moon"


def test_moon_position_depends_on_the_observer_site() -> None:
    """Parallax: seen from the surface the Moon is up to ~1° from its geocentric position."""
    when = datetime(2026, 10, 26, 4, 12, tzinfo=timezone.utc)
    geo = solar_system.search("moon", when=when)[0]
    topo = solar_system.search("moon", when=when, site=(50.8, 4.4, 100.0))[0]
    sep = _angular_sep_deg(geo["ra"], geo["dec"], topo["ra"], topo["dec"])
    assert 0.2 < sep < 1.5


def test_a_planet_barely_moves_with_the_site() -> None:
    when = datetime(2026, 10, 26, 4, 12, tzinfo=timezone.utc)
    geo = solar_system.search("jupiter", when=when)[0]
    topo = solar_system.search("jupiter", when=when, site=(50.8, 4.4, 100.0))[0]
    assert _angular_sep_deg(geo["ra"], geo["dec"], topo["ra"], topo["dec"]) < 0.01


def test_active_site_comes_from_the_active_profile(tmp_path) -> None:
    from types import SimpleNamespace

    from astrolol.equipment.models import SiteItem
    from astrolol.equipment.store import EquipmentStore
    from astrolol.plugins.object_resolver.service import active_site
    from astrolol.profiles.models import Profile, ProfileNode

    store = EquipmentStore(tmp_path / "inv.json")
    site = store.create(SiteItem(name="Home", latitude=50.8, longitude=4.4, altitude=100.0))
    app = SimpleNamespace(state=SimpleNamespace(
        active_profile=Profile(name="p", roots=[ProfileNode(item_id=site.id)]), equipment_store=store))
    assert active_site(app) == (50.8, 4.4, 100.0)
    app.state.active_profile = None
    assert active_site(app) is None
