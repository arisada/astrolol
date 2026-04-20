"""Tests for the object_resolver plugin API."""
from __future__ import annotations

from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from plugins.object_resolver.api import router
from plugins.object_resolver.catalog import ObjectCatalog
from plugins.object_resolver.settings import ObjectResolverSettings

# ── Minimal OpenNGC CSV fixture ────────────────────────────────────────────────

# Column order matches OpenNGC NGC.csv exactly.
_COLS = [
    "Name", "Type", "RA", "Dec", "Const", "MajAx", "MinAx", "PosAng",
    "B-Mag", "V-Mag", "J-Mag", "H-Mag", "K-Mag", "SurfBr", "Hubble",
    "Pax", "Pm-RA", "Pm-Dec", "RadVel", "Redshift", "Cz",
    "M", "NGC", "IC", "Cstar U-Mag", "Cstar B-Mag", "Cstar V-Mag",
    "Identifiers", "Common names", "NED notes", "OpenNGC notes",
]
_HEADER = ";".join(_COLS)


def _row(**kwargs: str) -> str:
    return ";".join(kwargs.get(c, "") for c in _COLS)


MINIMAL_CSV = "\n".join([
    _HEADER,
    # NGC 224 = M31 = Andromeda Galaxy  (RA ≈ 10.685°, Dec ≈ +41.269°)
    _row(Name="NGC0224", Type="G",   RA="00:42:44.30", Dec="+41:16:09.4",
         M="31", **{"Common names": "Andromeda Galaxy"}),
    # NGC 1952 = M1 = Crab Nebula  (RA ≈ 83.633°, Dec ≈ +22.015°)
    _row(Name="NGC1952", Type="SNR", RA="05:34:31.97", Dec="+22:00:52.1",
         M="1",  **{"Common names": "Crab Nebula"}),
    # NGC 5128 = Centaurus A  (RA ≈ 201.365°, Dec ≈ -43.019°)
    _row(Name="NGC5128", Type="G",   RA="13:25:27.62", Dec="-43:01:08.8",
         **{"Common names": "Centaurus A"}),
    # Non-existent entry — must be skipped
    _row(Name="NGC9999", Type="NonEx", RA="00:00:00.00", Dec="+00:00:00.0"),
    # Duplicate entry — must be skipped
    _row(Name="IC0001", Type="Dup",  RA="00:08:27.60", Dec="+27:42:50.0"),
])


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def catalog(tmp_path: Path) -> Generator[ObjectCatalog, None, None]:
    cat = ObjectCatalog(tmp_path / "test.db")
    cat.open()
    cat.load_csv(MINIMAL_CSV)
    yield cat
    cat.close()


def _make_app(catalog: ObjectCatalog, simbad_fallback: bool = False) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.object_resolver_catalog = catalog
    app.state.object_resolver_settings = ObjectResolverSettings(
        simbad_fallback=simbad_fallback
    )
    app.state.object_resolver_syncing = False
    return app


@pytest.fixture()
def client(catalog: ObjectCatalog) -> TestClient:
    return TestClient(_make_app(catalog))


# ── Status ─────────────────────────────────────────────────────────────────────

def test_status_populated(client: TestClient) -> None:
    resp = client.get("/plugins/object_resolver/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ready"] is True
    assert data["object_count"] == 3   # NonEx + Dup are skipped
    assert data["last_updated"] is not None
    assert data["syncing"] is False


def test_status_empty(tmp_path: Path) -> None:
    cat = ObjectCatalog(tmp_path / "empty.db")
    cat.open()
    with TestClient(_make_app(cat)) as c:
        data = c.get("/plugins/object_resolver/status").json()
    cat.close()
    assert data["ready"] is False
    assert data["object_count"] == 0
    assert data["last_updated"] is None


# ── Sync ───────────────────────────────────────────────────────────────────────

def test_sync_accepted(client: TestClient, catalog: ObjectCatalog) -> None:
    with patch.object(catalog, "sync", new=AsyncMock(return_value=3)):
        resp = client.post("/plugins/object_resolver/sync")
    assert resp.status_code == 202
    assert resp.json()["status"] == "accepted"


def test_sync_conflict(client: TestClient) -> None:
    client.app.state.object_resolver_syncing = True  # type: ignore[union-attr]
    resp = client.post("/plugins/object_resolver/sync")
    assert resp.status_code == 409


# ── Search — catalog ───────────────────────────────────────────────────────────

def test_search_by_ngc(client: TestClient) -> None:
    resp = client.get("/plugins/object_resolver/search", params={"q": "NGC 224"})
    assert resp.status_code == 200
    assert any(r["name"] == "NGC 224" for r in resp.json())


def test_search_by_messier_alias(client: TestClient) -> None:
    resp = client.get("/plugins/object_resolver/search", params={"q": "M31"})
    assert resp.status_code == 200
    assert any(r["name"] == "NGC 224" for r in resp.json())


def test_search_by_messier_with_space(client: TestClient) -> None:
    resp = client.get("/plugins/object_resolver/search", params={"q": "M 31"})
    assert resp.status_code == 200
    assert any(r["name"] == "NGC 224" for r in resp.json())


def test_search_by_common_name(client: TestClient) -> None:
    resp = client.get("/plugins/object_resolver/search", params={"q": "Andromeda"})
    assert resp.status_code == 200
    assert any(r["name"] == "NGC 224" for r in resp.json())


def test_search_result_includes_aliases(client: TestClient) -> None:
    resp = client.get("/plugins/object_resolver/search", params={"q": "M31"})
    assert resp.status_code == 200
    match = next(r for r in resp.json() if r["name"] == "NGC 224")
    assert "Andromeda Galaxy" in match["aliases"]
    assert any(a.startswith("M") for a in match["aliases"])


def test_search_result_source_is_catalog(client: TestClient) -> None:
    resp = client.get("/plugins/object_resolver/search", params={"q": "NGC 224"})
    assert resp.status_code == 200
    match = next(r for r in resp.json() if r["name"] == "NGC 224")
    assert match["source"] == "catalog"


def test_search_no_catalog_results(client: TestClient) -> None:
    resp = client.get("/plugins/object_resolver/search", params={"q": "xyzzy_no_match_12345"})
    assert resp.status_code == 200
    assert all(r["source"] != "catalog" for r in resp.json())


def test_search_missing_query_param(client: TestClient) -> None:
    resp = client.get("/plugins/object_resolver/search")
    assert resp.status_code == 422


def test_search_skipped_types_not_returned(client: TestClient) -> None:
    # NGC9999 (NonEx) and IC1 (Dup) must not appear in results
    resp = client.get("/plugins/object_resolver/search", params={"q": "NGC9999"})
    assert resp.status_code == 200
    assert all(r["name"] != "NGC 9999" for r in resp.json())


# ── Search — solar system ──────────────────────────────────────────────────────

def test_search_planet_returns_coordinates(client: TestClient) -> None:
    resp = client.get("/plugins/object_resolver/search", params={"q": "Mars"})
    assert resp.status_code == 200
    ss = [r for r in resp.json() if r["source"] == "solar_system"]
    assert len(ss) == 1
    assert ss[0]["name"] == "Mars"
    assert isinstance(ss[0]["ra"], float)
    assert isinstance(ss[0]["dec"], float)
    assert ss[0]["type"] == "Solar System"


def test_search_moon(client: TestClient) -> None:
    resp = client.get("/plugins/object_resolver/search", params={"q": "Moon"})
    assert resp.status_code == 200
    assert any(r["name"] == "Moon" for r in resp.json())


def test_search_when_parameter_accepted(client: TestClient) -> None:
    resp = client.get(
        "/plugins/object_resolver/search",
        params={"q": "Saturn", "when": "2025-06-21T22:00:00Z"},
    )
    assert resp.status_code == 200
    assert any(r["name"] == "Saturn" for r in resp.json())


def test_search_invalid_when(client: TestClient) -> None:
    resp = client.get(
        "/plugins/object_resolver/search",
        params={"q": "Mars", "when": "not-a-date"},
    )
    assert resp.status_code == 422


# ── Resolve (cone search) ──────────────────────────────────────────────────────

def test_resolve_near_andromeda(client: TestClient) -> None:
    # NGC 224 is at RA ≈ 10.685°, Dec ≈ +41.269°
    resp = client.get(
        "/plugins/object_resolver/resolve",
        params={"ra": 10.685, "dec": 41.269, "radius": 5.0},
    )
    assert resp.status_code == 200
    assert any(r["name"] == "NGC 224" for r in resp.json())


def test_resolve_distance_present(client: TestClient) -> None:
    resp = client.get(
        "/plugins/object_resolver/resolve",
        params={"ra": 10.685, "dec": 41.269, "radius": 10.0},
    )
    assert resp.status_code == 200
    for r in resp.json():
        assert r["distance_arcmin"] is not None


def test_resolve_sorted_by_distance(client: TestClient) -> None:
    # Wide search — Andromeda and Crab Nebula are far apart, but within 180°
    resp = client.get(
        "/plugins/object_resolver/resolve",
        params={"ra": 10.685, "dec": 41.269, "radius": 600.0},
    )
    assert resp.status_code == 200
    catalog_results = [r for r in resp.json() if r["source"] == "catalog"]
    distances = [r["distance_arcmin"] for r in catalog_results]
    assert distances == sorted(distances)


def test_resolve_empty_region(client: TestClient) -> None:
    # Point with no test objects within 1 arcminute
    resp = client.get(
        "/plugins/object_resolver/resolve",
        params={"ra": 180.0, "dec": 0.0, "radius": 1.0},
    )
    assert resp.status_code == 200
    catalog_results = [r for r in resp.json() if r["source"] == "catalog"]
    assert catalog_results == []


# ── Simbad fallback ────────────────────────────────────────────────────────────

def test_simbad_not_called_when_disabled(client: TestClient) -> None:
    with patch(
        "plugins.object_resolver.simbad.resolve",
        new=AsyncMock(return_value=None),
    ) as mock_resolve:
        client.get("/plugins/object_resolver/search", params={"q": "xyzzy_no_match"})
    mock_resolve.assert_not_called()


def test_simbad_called_when_enabled_and_no_results(tmp_path: Path) -> None:
    cat = ObjectCatalog(tmp_path / "simbad.db")
    cat.open()
    cat.load_csv(MINIMAL_CSV)
    fake = {
        "name": "ExoticObject",
        "aliases": [],
        "type": "Galaxy",
        "ra": 99.0,
        "dec": -10.0,
        "source": "simbad",
    }
    with patch("plugins.object_resolver.simbad.resolve", new=AsyncMock(return_value=fake)):
        with TestClient(_make_app(cat, simbad_fallback=True)) as c:
            resp = c.get("/plugins/object_resolver/search", params={"q": "xyzzy_no_match"})
    cat.close()
    assert resp.status_code == 200
    assert any(r["source"] == "simbad" for r in resp.json())


def test_simbad_not_called_when_local_results_exist(tmp_path: Path) -> None:
    cat = ObjectCatalog(tmp_path / "simbad2.db")
    cat.open()
    cat.load_csv(MINIMAL_CSV)
    with patch(
        "plugins.object_resolver.simbad.resolve",
        new=AsyncMock(return_value=None),
    ) as mock_resolve:
        with TestClient(_make_app(cat, simbad_fallback=True)) as c:
            c.get("/plugins/object_resolver/search", params={"q": "Andromeda"})
    cat.close()
    mock_resolve.assert_not_called()
