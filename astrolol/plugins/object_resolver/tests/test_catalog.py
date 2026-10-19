"""Tests for ObjectCatalog: Sharpless and Hipparcos loaders, and combined sync."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Generator
from unittest.mock import AsyncMock, patch

import pytest

from astrolol.plugins.object_resolver.catalog import ObjectCatalog, _parse_vizier_tsv

# ── Minimal VizieR TSV fixtures (real ASU -tsv layout: comments, header, ─────────
# units, dashes, then tab-separated data) ────────────────────────────────────────

SHARPLESS_TSV = "\n".join([
    "#",
    "#   VizieR Astronomical Server vizier.cds.unistra.fr",
    "#Table\tVII_20_catalog:",
    "#Column\tSh2\t(I4)\t[1/313]+ Sharpless HII catalog number",
    "_RAJ2000\t_DEJ2000\tSh2\tDiam",
    "deg\tdeg\t \tarcmin",
    "----------\t----------\t----\t----",
    "239.713380\t-26.120461\t   1\t 150",
    "256.027575\t-38.142463\t   2\t  60",
])

HIPPARCOS_TSV = "\n".join([
    "#",
    "#   VizieR Astronomical Server vizier.cds.unistra.fr",
    "#Table\tI_239_hip_main:",
    "#Column\tHIP\t(I6)\tIdentifier (HIP number)",
    "HIP\tRAICRS\tDEICRS\tVmag",
    " \tdeg\tdeg\tmag",
    "------\t------------\t------------\t-----",
    "     1\t000.00091185\t+01.08901332\t 9.10",
    "     3\t000.00500795\t+38.85928608\t 6.61",
    # A row missing a required field must be skipped, not crash the loader.
    "     4\t\t-51.89354612\t 8.06",
])

# Column order matches OpenNGC NGC.csv exactly (mirrors test_object_resolver_api.py).
_NGC_COLS = [
    "Name", "Type", "RA", "Dec", "Const", "MajAx", "MinAx", "PosAng",
    "B-Mag", "V-Mag", "J-Mag", "H-Mag", "K-Mag", "SurfBr", "Hubble",
    "Pax", "Pm-RA", "Pm-Dec", "RadVel", "Redshift", "Cz",
    "M", "NGC", "IC", "Cstar U-Mag", "Cstar B-Mag", "Cstar V-Mag",
    "Identifiers", "Common names", "NED notes", "OpenNGC notes",
]
_NGC_HEADER = ";".join(_NGC_COLS)


def _ngc_row(**kwargs: str) -> str:
    return ";".join(kwargs.get(c, "") for c in _NGC_COLS)


NGC_CSV = "\n".join([
    _NGC_HEADER,
    # IC 1 (RA ≈ 2.107°, Dec ≈ +27.714°)
    _ngc_row(Name="IC0001", Type="G", RA="00:08:27.00", Dec="+27:42:50.0"),
])


@pytest.fixture()
def catalog(tmp_path: Path) -> Generator[ObjectCatalog, None, None]:
    cat = ObjectCatalog(tmp_path / "test.db")
    cat.open()
    yield cat
    cat.close()


# ── _parse_vizier_tsv ────────────────────────────────────────────────────────────

def test_parse_vizier_tsv_skips_comments_and_units() -> None:
    rows = _parse_vizier_tsv(SHARPLESS_TSV)
    assert len(rows) == 2
    assert rows[0] == {"_RAJ2000": "239.713380", "_DEJ2000": "-26.120461", "Sh2": "1", "Diam": "150"}


def test_parse_vizier_tsv_empty_content_returns_empty() -> None:
    assert _parse_vizier_tsv("") == []
    assert _parse_vizier_tsv("# only comments\n#more") == []


# ── IC objects (already supported by OpenNGC, but easy to regress) ──────────────

def test_ic_object_is_searchable(catalog: ObjectCatalog) -> None:
    catalog.load_csv(NGC_CSV)
    results = catalog.search("IC 1")
    assert any(r["name"] == "IC 1" for r in results)


def test_ic_object_alias_without_space(catalog: ObjectCatalog) -> None:
    catalog.load_csv(NGC_CSV)
    results = catalog.search("IC1")
    assert any(r["name"] == "IC 1" for r in results)


# ── Sharpless ─────────────────────────────────────────────────────────────────

def test_load_sharpless_tsv_count(catalog: ObjectCatalog) -> None:
    count = catalog.load_sharpless_tsv(SHARPLESS_TSV)
    assert count == 2
    assert catalog.object_count() == 2


def test_sharpless_object_fields(catalog: ObjectCatalog) -> None:
    catalog.load_sharpless_tsv(SHARPLESS_TSV)
    results = catalog.search("Sh2-1")
    match = next(r for r in results if r["name"] == "Sh2-1")
    assert match["type"] == "HII Region"
    assert match["ra"] == pytest.approx(239.713380)
    assert match["dec"] == pytest.approx(-26.120461)


def test_sharpless_alias_variants(catalog: ObjectCatalog) -> None:
    catalog.load_sharpless_tsv(SHARPLESS_TSV)
    for query in ("Sh2-1", "Sh2 1", "SH2-1", "Sharpless 1", "Sharpless-1"):
        results = catalog.search(query)
        assert any(r["name"] == "Sh2-1" for r in results), f"query {query!r} found no match"


# ── Hipparcos ─────────────────────────────────────────────────────────────────

def test_load_hipparcos_tsv_count(catalog: ObjectCatalog) -> None:
    # Row HIP 4 is missing RA and must be skipped.
    count = catalog.load_hipparcos_tsv(HIPPARCOS_TSV)
    assert count == 2
    assert catalog.object_count() == 2


def test_hipparcos_object_fields(catalog: ObjectCatalog) -> None:
    catalog.load_hipparcos_tsv(HIPPARCOS_TSV)
    results = catalog.search("HIP 1")
    match = next(r for r in results if r["name"] == "HIP 1")
    assert match["type"] == "Star"
    assert match["ra"] == pytest.approx(0.00091185)
    assert match["dec"] == pytest.approx(1.08901332)


def test_hipparcos_alias_without_space(catalog: ObjectCatalog) -> None:
    catalog.load_hipparcos_tsv(HIPPARCOS_TSV)
    results = catalog.search("HIP3")
    assert any(r["name"] == "HIP 3" for r in results)


# ── Combined sync() ────────────────────────────────────────────────────────────

def test_sync_combines_all_three_catalogs(catalog: ObjectCatalog) -> None:
    async def _fake_download(url: str) -> str:
        if "OpenNGC" in url:
            return NGC_CSV
        if "VII/20" in url:
            return SHARPLESS_TSV
        if "hip_main" in url:
            return HIPPARCOS_TSV
        raise AssertionError(f"unexpected url {url}")

    with patch.object(catalog, "_download", new=AsyncMock(side_effect=_fake_download)):
        count = asyncio.run(catalog.sync())

    # 1 IC object + 2 Sharpless + 2 Hipparcos (1 HIP row is skipped for missing RA)
    assert count == 5
    assert catalog.object_count() == 5
    assert any(r["name"] == "IC 1" for r in catalog.search("IC 1"))
    assert any(r["name"] == "Sh2-1" for r in catalog.search("Sh2-1"))
    assert any(r["name"] == "HIP 1" for r in catalog.search("HIP 1"))


# ── Proper names of bright stars ───────────────────────────────────────────────

def test_named_stars_are_found_after_a_hipparcos_load(catalog: ObjectCatalog) -> None:
    vega = "\n".join([
        "HIP\tRAICRS\tDEICRS\tVmag", " \tdeg\tdeg\tmag", "------\t------\t------\t-----",
        " 91262\t279.23410832\t+38.78299311\t 0.03",
        " 32349\t101.28854105\t-16.71314306\t-1.44",
    ])
    catalog.load_hipparcos_tsv(vega)
    catalog.apply_star_names()
    hit = catalog.search("vega")[0]
    assert hit["name"] == "HIP 91262"
    assert [r["name"] for r in catalog.search("Dog Star")] == ["HIP 32349"]


def test_star_names_are_added_to_an_existing_catalogue_on_open(tmp_path: Path) -> None:
    cat = ObjectCatalog(tmp_path / "old.db")
    cat.open()
    cat.load_hipparcos_tsv("\n".join([
        "HIP\tRAICRS\tDEICRS\tVmag", " \tdeg\tdeg\tmag", "------\t------\t------\t-----",
        " 11767\t37.94614689\t+89.26413805\t 2.0",
    ]))
    assert cat.search("Polaris") == []  # a catalogue synced before names existed
    cat.close()
    cat.open()
    assert cat.search("Polaris")[0]["name"] == "HIP 11767"
    cat.close()


def test_star_names_table_has_no_duplicate_hip_numbers() -> None:
    from astrolol.plugins.object_resolver.star_names import STAR_NAMES
    assert len(set(STAR_NAMES.values())) == len(STAR_NAMES)


# ── Duplicate rows, Caldwell numbers, ranking, refresh ─────────────────────────

def test_a_repeated_catalogue_row_keeps_the_names_of_the_first(catalog: ObjectCatalog) -> None:
    csv = "\n".join([
        _NGC_HEADER,
        _ngc_row(Name="NGC4945", Type="G", RA="13:05:27.00", Dec="-49:41:26.0", **{"Common names": "Foo"}),
        _ngc_row(Name="NGC4945", Type="G", RA="13:05:27.00", Dec="-49:41:26.0"),
    ])
    catalog.load_csv(csv)
    assert [r["name"] for r in catalog.search("Foo")] == ["NGC 4945"]
    assert catalog.search("NGC 4945")


def test_caldwell_numbers_are_added_in_every_spelling(catalog: ObjectCatalog) -> None:
    catalog.load_csv("\n".join([
        _NGC_HEADER,
        _ngc_row(Name="NGC4945", Type="G", RA="13:05:27.00", Dec="-49:41:26.0"),
        _ngc_row(Name="NGC0869", Type="OC", RA="02:19:00.00", Dec="+57:08:00.0"),
        _ngc_row(Name="NGC0884", Type="OC", RA="02:22:00.00", Dec="+57:08:00.0"),
    ]))
    catalog.apply_caldwell()
    for q in ("C 83", "C83", "Caldwell 83"):
        assert catalog.search(q)[0]["name"] == "NGC 4945"
    assert catalog.search("Caldwell 14")[0]["name"] == "NGC 869"  # the Double Cluster, first member


def test_caldwell_objects_without_another_catalogue_are_created(catalog: ObjectCatalog) -> None:
    catalog.load_csv(NGC_CSV)
    catalog.apply_caldwell()
    assert catalog.search("Coalsack")[0]["type"] == "Dark Nebula"
    assert catalog.search("C 41")[0]["name"] == "Mel 25"
    assert "Hyades" in catalog.search("C 41")[0]["aliases"]


def test_exact_name_ranks_before_substring_matches(catalog: ObjectCatalog) -> None:
    catalog.load_csv("\n".join([
        _NGC_HEADER,
        _ngc_row(Name="IC0083", Type="G", RA="00:08:00.00", Dec="+10:00:00.0"),
        _ngc_row(Name="NGC4945", Type="G", RA="13:05:27.00", Dec="-49:41:26.0"),
    ]))
    catalog.apply_caldwell()
    assert [r["name"] for r in catalog.search("C 83")][0] == "NGC 4945"


def test_old_databases_are_flagged_for_refresh(catalog: ObjectCatalog) -> None:
    catalog._load_all(NGC_CSV, SHARPLESS_TSV, HIPPARCOS_TSV)
    assert not catalog.needs_refresh()
    catalog._conn.execute("DELETE FROM catalog_meta WHERE key='data_version'")
    assert catalog.needs_refresh()


# --- magnitude, size, the well-known flag, double stars ---

_NGC_WITH_DATA = "\n".join([
    _NGC_HEADER,
    _ngc_row(Name="NGC0224", Type="G", RA="00:42:44.30", Dec="+41:16:09.4", MajAx="177.83",
             **{"V-Mag": "3.44", "B-Mag": "4.36", "M": "31", "Common names": "Andromeda Galaxy"}),
    _ngc_row(Name="NGC0100", Type="G", RA="00:21:00.00", Dec="+05:00:00.0", MajAx="3.2",
             **{"B-Mag": "13.1"}),
    _ngc_row(Name="NGC0200", Type="G", RA="00:30:00.00", Dec="+05:00:00.0"),
    _ngc_row(Name="NGC7000", Type="HII", RA="20:59:17.0", Dec="+44:31:44.0", MajAx="120",
             **{"Common names": "North America Nebula"}),
])


_CALDWELL_ONLY = {"Mel 25", "Coalsack"}   # created in every catalogue, and well known


def _notable(cat: ObjectCatalog, groups=None) -> set[str]:
    return {r["name"] for r in cat.notable(groups)} - _CALDWELL_ONLY


def test_magnitude_and_size_are_loaded(catalog: ObjectCatalog) -> None:
    catalog.load_csv(_NGC_WITH_DATA)
    by_name = {r["name"]: r for r in catalog.search("NGC")}
    assert by_name["NGC 224"]["mag"] == 3.44          # V magnitude when there is one
    assert by_name["NGC 224"]["size_arcmin"] == 177.83
    assert by_name["NGC 100"]["mag"] == 13.1          # else B
    assert by_name["NGC 200"]["mag"] is None and by_name["NGC 200"]["size_arcmin"] is None


def test_hipparcos_magnitude_is_loaded(catalog: ObjectCatalog) -> None:
    catalog.load_hipparcos_tsv(HIPPARCOS_TSV)
    assert catalog.search("HIP 3")[0]["mag"] == 6.61


def test_messier_and_named_objects_are_well_known_and_others_are_not(catalog: ObjectCatalog) -> None:
    catalog.load_csv(_NGC_WITH_DATA)
    catalog.apply_extra_names()
    assert _notable(catalog) == {"NGC 224", "NGC 7000"}


def test_caldwell_and_named_stars_are_well_known(catalog: ObjectCatalog) -> None:
    catalog.load_csv(_ngc_row_csv("NGC0188", "OC"))
    catalog.load_hipparcos_tsv("\n".join([
        "HIP\tRAICRS\tDEICRS\tVmag", " \tdeg\tdeg\tmag", "------\t------\t------\t-----",
        " 91262\t279.23410832\t+38.78299311\t 0.03",
        " 91263\t279.5\t+38.0\t 8.0",
    ]))
    catalog.apply_extra_names()
    names = _notable(catalog)
    assert "HIP 91262" in names          # Vega
    assert "HIP 91263" not in names      # an ordinary star


def _ngc_row_csv(name: str, kind: str) -> str:
    return "\n".join([_NGC_HEADER, _ngc_row(Name=name, Type=kind, RA="00:53:00.00", Dec="+85:15:00.0")])


def test_other_m_designations_are_not_messier(catalog: ObjectCatalog) -> None:
    """"M 1-20" (a planetary nebula) is not Messier 1."""
    catalog.load_csv("\n".join([
        _NGC_HEADER,
        _ngc_row(Name="IC0001", Type="PN", RA="07:30:00.00", Dec="-09:00:00.0", Identifiers="M 1-20"),
    ]))
    catalog.apply_extra_names()
    assert _notable(catalog) == set()


def test_showpiece_double_stars_are_marked_and_named(catalog: ObjectCatalog) -> None:
    catalog.load_hipparcos_tsv("\n".join([
        "HIP\tRAICRS\tDEICRS\tVmag", " \tdeg\tdeg\tmag", "------\t------\t------\t-----",
        " 95947\t292.68033548\t+27.95968190\t 3.18",
        " 91919\t281.08\t+39.67\t 5.0",
    ]))
    catalog.apply_extra_names()
    albireo = catalog.search("Albireo")[0]
    assert albireo["type"] == "Double Star"
    assert catalog.search("Double Double")[0]["name"] == "HIP 91919"
    assert {r["name"] for r in catalog.notable(["double_star"])} == {"HIP 95947", "HIP 91919"}


def test_double_star_table_points_at_distinct_known_stars() -> None:
    from astrolol.plugins.object_resolver.double_stars import DOUBLE_STARS

    assert len(DOUBLE_STARS) == len(set(DOUBLE_STARS))
    assert all(isinstance(h, int) and h > 0 for h in DOUBLE_STARS.values())


def test_notable_can_be_limited_to_kinds(catalog: ObjectCatalog) -> None:
    catalog.load_csv(_NGC_WITH_DATA)
    catalog.apply_extra_names()
    assert _notable(catalog, ["galaxy"]) == {"NGC 224"}
    assert _notable(catalog, ["nebula"]) == {"NGC 7000"}
    assert _notable(catalog, ["cluster"]) == set()


def test_a_database_without_the_new_columns_is_upgraded(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "v2.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE catalog_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE objects (id INTEGER PRIMARY KEY AUTOINCREMENT, primary_name TEXT NOT NULL UNIQUE,
            object_type TEXT NOT NULL DEFAULT '', ra REAL NOT NULL, dec REAL NOT NULL);
        CREATE TABLE object_names (name TEXT NOT NULL COLLATE NOCASE,
            object_id INTEGER NOT NULL REFERENCES objects(id), PRIMARY KEY (name));
        INSERT INTO objects (primary_name, object_type, ra, dec) VALUES ('NGC 224', 'Galaxy', 10.68, 41.27);
        INSERT INTO object_names (name, object_id) VALUES ('NGC 224', 1), ('M 31', 1);
        INSERT INTO catalog_meta VALUES ('object_count', '1'), ('data_version', '2');
    """)
    old.commit()
    old.close()

    cat = ObjectCatalog(path)
    cat.open()
    assert cat.needs_refresh()                 # version 2: refreshed in the background when online
    assert _notable(cat) == {"NGC 224"}   # Messier is known without a refresh
    assert cat.search("M 31")[0]["mag"] is None
    cat.close()
