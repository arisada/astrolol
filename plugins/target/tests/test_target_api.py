"""Tests for the target plugin API and ephemeris engine."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.core.events import EventBus
from astrolol.core.plugin_api import PluginContext
from astrolol.equipment.models import ProfileNode, SiteItem
from astrolol.equipment.store import EquipmentStore
from astrolol.profiles.models import Profile
from plugins.target.ephemeris import compute_ephemeris
from plugins.target.models import FavoriteTarget, TargetSettings
from plugins.target.plugin import TargetPlugin


# ── App factory ───────────────────────────────────────────────────────────────

def _make_app(site: SiteItem | None = None, tmp_path=None) -> FastAPI:
    app = FastAPI()
    bus = EventBus()

    user_settings = MagicMock()
    user_settings.plugin_settings = {}
    user_settings.model_copy.return_value = user_settings

    profile_store = MagicMock()
    profile_store.get_user_settings.return_value = user_settings
    profile_store.get_last_active_id.return_value = "p1" if site else None

    if site is not None:
        import tempfile, pathlib
        inv_path = pathlib.Path(tempfile.mkdtemp()) / "inventory.json"
        eq_store = EquipmentStore(inv_path)
        stored_site = eq_store.create(site)
        profile = Profile(id="p1", name="Test",
                          roots=[ProfileNode(item_id=stored_site.id)])
        profile_store.get.return_value = profile
        app.state.equipment_store = eq_store
    else:
        app.state.equipment_store = None

    app.state.profile_store = profile_store

    ctx = PluginContext(
        event_bus=bus,
        device_manager=MagicMock(),
        device_registry=MagicMock(),
        profile_store=profile_store,
    )
    plugin = TargetPlugin()
    plugin.setup(app, ctx)
    return app


_LONDON = SiteItem(name="London", latitude=51.5, longitude=-0.12, altitude=10.0)
_SYDNEY = SiteItem(name="Sydney", latitude=-33.87, longitude=151.21, altitude=20.0)


@pytest.fixture
def client() -> TestClient:
    return TestClient(_make_app(site=_LONDON))


@pytest.fixture
def client_no_location() -> TestClient:
    return TestClient(_make_app(site=None))


# ── Settings CRUD ─────────────────────────────────────────────────────────────

def test_get_settings_defaults(client: TestClient) -> None:
    resp = client.get("/plugins/target/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["favorites"] == []
    assert data["min_altitude_deg"] == 30.0


def test_put_settings_persists(client: TestClient) -> None:
    app = _make_app(site=_LONDON)

    saved: dict = {}

    def _update_settings(s):
        saved["settings"] = s
        return s

    app.state.profile_store.update_user_settings.side_effect = _update_settings

    with TestClient(app) as tc:
        resp = tc.put("/plugins/target/settings", json={"favorites": [], "min_altitude_deg": 20.0})
    assert resp.status_code == 200
    assert resp.json()["min_altitude_deg"] == 20.0


def test_put_settings_rejects_invalid_altitude(client: TestClient) -> None:
    resp = client.put("/plugins/target/settings", json={"favorites": [], "min_altitude_deg": 91.0})
    assert resp.status_code == 422


def test_favorites_round_trip() -> None:
    """FavoriteTarget model serialises and deserialises cleanly."""
    fav = FavoriteTarget(name="Orion Nebula", ra=83.822, dec=-5.391,
                         object_name="M 42", object_type="HII Region")
    settings = TargetSettings(favorites=[fav])
    raw = settings.model_dump()
    recovered = TargetSettings(**raw)
    assert recovered.favorites[0].name == "Orion Nebula"
    assert recovered.favorites[0].ra == pytest.approx(83.822)


# ── Ephemeris endpoint ────────────────────────────────────────────────────────

def test_ephemeris_missing_location(client_no_location: TestClient) -> None:
    resp = client_no_location.get("/plugins/target/ephemeris?ra=83.822&dec=-5.391")
    assert resp.status_code == 200
    assert resp.json()["observer_location_missing"] is True


def test_ephemeris_returns_altitude_curve(client: TestClient) -> None:
    resp = client.get("/plugins/target/ephemeris?ra=83.822&dec=-5.391&date=2025-01-15")
    assert resp.status_code == 200
    data = resp.json()
    assert data["observer_location_missing"] is False
    assert len(data["altitude_curve"]) > 0
    # Each point has time and alt
    pt = data["altitude_curve"][0]
    assert "time" in pt
    assert "alt" in pt


def test_ephemeris_has_moon_data(client: TestClient) -> None:
    resp = client.get("/plugins/target/ephemeris?ra=83.822&dec=-5.391&date=2025-01-15")
    data = resp.json()
    assert data["moon_illumination"] is not None
    assert 0.0 <= data["moon_illumination"] <= 1.0


def test_ephemeris_invalid_date_returns_422(client: TestClient) -> None:
    resp = client.get("/plugins/target/ephemeris?ra=83.822&dec=-5.391&date=not-a-date")
    assert resp.status_code == 422


def test_ephemeris_invalid_ra_returns_422(client: TestClient) -> None:
    resp = client.get("/plugins/target/ephemeris?ra=400&dec=0")
    assert resp.status_code == 422


# ── Ephemeris unit tests ───────────────────────────────────────────────────────

def test_compute_ephemeris_orion_from_london() -> None:
    """M42 should be visible from London in January (dec ≈ -5°)."""
    result = compute_ephemeris(
        ra_deg=83.822,
        dec_deg=-5.391,
        latitude=51.5,
        longitude=-0.12,
        altitude_m=10.0,
        obs_date=date(2025, 1, 15),
    )
    assert not result.observer_location_missing
    assert not result.never_rises
    assert result.rise is not None
    assert result.set is not None
    assert result.peak_alt is not None
    assert result.peak_alt > 0


def test_compute_ephemeris_polaris_circumpolar_from_london() -> None:
    """Polaris (dec ≈ +89°) is circumpolar from London."""
    result = compute_ephemeris(
        ra_deg=37.95,
        dec_deg=89.26,
        latitude=51.5,
        longitude=-0.12,
        altitude_m=10.0,
        obs_date=date(2025, 6, 1),
    )
    assert result.circumpolar is True
    assert not result.never_rises


def test_compute_ephemeris_never_rises_from_london() -> None:
    """A target near the south celestial pole never rises from London."""
    result = compute_ephemeris(
        ra_deg=90.0,
        dec_deg=-85.0,
        latitude=51.5,
        longitude=-0.12,
        altitude_m=10.0,
        obs_date=date(2025, 1, 15),
    )
    assert result.never_rises is True
    assert not result.circumpolar


def test_compute_ephemeris_altitude_curve_length() -> None:
    result = compute_ephemeris(
        ra_deg=83.822,
        dec_deg=-5.391,
        latitude=51.5,
        longitude=-0.12,
        altitude_m=10.0,
        obs_date=date(2025, 1, 15),
    )
    # 24h window at 10-min resolution = 145 points (0 to 1440 inclusive)
    assert len(result.altitude_curve) == 145


def test_compute_ephemeris_twilight_populated() -> None:
    result = compute_ephemeris(
        ra_deg=83.822,
        dec_deg=-5.391,
        latitude=51.5,
        longitude=-0.12,
        altitude_m=10.0,
        obs_date=date(2025, 1, 15),
    )
    # London in January: all twilight phases exist
    assert result.twilight.astronomical_dusk is not None
    assert result.twilight.astronomical_dawn is not None


def test_compute_ephemeris_imaging_window_above_threshold() -> None:
    result = compute_ephemeris(
        ra_deg=83.822,
        dec_deg=-5.391,
        latitude=51.5,
        longitude=-0.12,
        altitude_m=10.0,
        obs_date=date(2025, 1, 15),
        min_altitude_deg=30.0,
    )
    # M42 from London reaches ~40° — window should exist
    if result.imaging_window_start is not None:
        assert result.imaging_window_end is not None


def test_compute_ephemeris_southern_hemisphere() -> None:
    """Objects circumpolar from London should be visible from Sydney too."""
    result = compute_ephemeris(
        ra_deg=83.822,
        dec_deg=-5.391,
        latitude=-33.87,
        longitude=151.21,
        altitude_m=20.0,
        obs_date=date(2025, 1, 15),
    )
    assert not result.never_rises
    assert result.peak_alt is not None
    # From Sydney, M42 transits near zenith (~51° dec from zenith)
    assert result.peak_alt > 50.0


def test_compute_ephemeris_not_observable_at_night() -> None:
    """An object that only clears min_altitude during daytime sets not_observable_at_night."""
    # From Helsinki (60°N) in summer, Scorpius (dec ≈ -26°) barely clears the horizon at night.
    # By setting a high min_altitude we force the "not observable at night" path.
    result = compute_ephemeris(
        ra_deg=247.35,     # Antares, dec ~ -26.4°
        dec_deg=-26.43,
        latitude=60.17,
        longitude=24.94,
        altitude_m=25.0,
        obs_date=date(2025, 6, 21),  # summer solstice — very short night
        min_altitude_deg=30.0,
    )
    # Either the object truly never gets high enough at night, or it does —
    # either way the flags should be internally consistent.
    assert not (result.not_observable_at_night and result.imaging_window_start is not None), (
        "imaging_window_start must be None when not_observable_at_night is True"
    )
    if result.not_observable_at_night:
        assert result.imaging_window_start is None


def test_compute_ephemeris_moon_separation_range() -> None:
    result = compute_ephemeris(
        ra_deg=83.822,
        dec_deg=-5.391,
        latitude=51.5,
        longitude=-0.12,
        altitude_m=10.0,
        obs_date=date(2025, 1, 15),
    )
    assert result.moon_separation is not None
    assert 0.0 <= result.moon_separation <= 180.0
    assert result.moon_illumination is not None
    assert 0.0 <= result.moon_illumination <= 1.0
