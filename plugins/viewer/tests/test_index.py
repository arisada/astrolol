from datetime import datetime, timezone
from pathlib import Path

import pytest

from plugins.viewer.index import ImageFilters, RescanInProgress, ViewerIndex, _delete_stale
from plugins.viewer.tests.helpers import write_fits


def _std_header(**overrides) -> dict:
    base = dict(
        IMAGETYP="Light Frame", OBJECT="M42", EXPTIME=300.0, GAIN=100, XBINNING=1,
        FILTER="Ha", INSTRUME="cam1", **{"DATE-OBS": "2026-09-29T22:00:00"},
    )
    base.update(overrides)
    return base


@pytest.fixture
async def index(tmp_path: Path) -> ViewerIndex:
    idx = ViewerIndex(tmp_path / "index.sqlite3")
    await idx.start()
    yield idx
    await idx.close()


@pytest.mark.asyncio
async def test_scan_indexes_new_files(index: ViewerIndex, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    write_fits(lib / "a.fits", **_std_header(OBJECT="M42"))
    write_fits(lib / "b.fits", **_std_header(OBJECT="M31"))

    result = await index.scan(lib)

    assert result.added == 2
    assert result.updated == 0
    assert result.removed == 0
    items, total = await index.list_images(ImageFilters(), limit=50)
    assert total == 2


@pytest.mark.asyncio
async def test_rescan_skips_unchanged_files(index: ViewerIndex, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    write_fits(lib / "a.fits", **_std_header())
    await index.scan(lib)

    result = await index.scan(lib)
    assert result.added == 0
    assert result.updated == 0


@pytest.mark.asyncio
async def test_rescan_picks_up_a_changed_file(index: ViewerIndex, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    path = write_fits(lib / "a.fits", **_std_header(OBJECT="M42"))
    await index.scan(lib)

    write_fits(path, **_std_header(OBJECT="M31"))
    result = await index.scan(lib)

    assert result.updated == 1
    items, _ = await index.list_images(ImageFilters(), limit=50)
    assert items[0].object_name == "M31"


@pytest.mark.asyncio
async def test_rescan_removes_deleted_files(index: ViewerIndex, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    path = write_fits(lib / "a.fits", **_std_header())
    await index.scan(lib)

    path.unlink()
    result = await index.scan(lib)

    assert result.removed == 1
    _, total = await index.list_images(ImageFilters(), limit=50)
    assert total == 0


@pytest.mark.asyncio
async def test_single_flight_rescan_rejects_a_second_concurrent_scan(index: ViewerIndex, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    for i in range(50):
        write_fits(lib / f"{i:03d}.fits", **_std_header(OBJECT=f"obj{i}"))

    task = index.start_rescan(lib)
    with pytest.raises(RescanInProgress):
        index.start_rescan(lib)
    await task


@pytest.mark.asyncio
async def test_generation_guard_protects_a_row_written_during_the_walk(index: ViewerIndex, tmp_path: Path) -> None:
    """The core rescan/live-indexer race fix: a row written mid-walk by the live
    indexer must not be deleted by that same walk's "remove stale rows" step."""
    lib = tmp_path / "lib"
    stale_path = write_fits(lib / "stale.fits", **_std_header())
    await index.scan(lib)  # generation becomes 1; stale.fits stamped with gen 1

    # Simulate: a rescan bumps to generation 2, and *during* its walk, the live
    # indexer inserts a brand-new file stamped with that same current generation —
    # exactly what plugin.py's _LiveIndexer does via index_file().
    index._generation = 2
    live_path = write_fits(lib / "live_during_scan.fits", **_std_header(OBJECT="Live"))
    await index.index_file(live_path)

    removed = await index._run(lambda c: _delete_stale(c, str(lib), 2))

    assert removed == 1  # stale.fits (generation 1) is gone
    survivor = await index.get_by_path(live_path)
    assert survivor is not None  # live_during_scan.fits (generation 2) survived


@pytest.mark.asyncio
async def test_list_groups_aggregates_a_session(index: ViewerIndex, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    for i in range(3):
        write_fits(lib / f"m42_{i}.fits", **_std_header(OBJECT="M42", EXPTIME=300.0))
    write_fits(lib / "m31_0.fits", **_std_header(OBJECT="M31", EXPTIME=180.0))
    await index.scan(lib)

    groups, total = await index.list_groups(ImageFilters(), page=1, page_size=50)

    assert total == 2
    m42_group = next(g for g in groups if g.object_name == "M42")
    assert m42_group.count == 3
    assert m42_group.total_exposure_s == 900.0
    assert m42_group.representative_id


@pytest.mark.asyncio
async def test_two_untracked_targets_same_night_produce_two_groups(index: ViewerIndex, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    write_fits(lib / "a.fits", **_std_header(OBJECT="", **{"RA": 10.0, "DEC": 20.0}))
    write_fits(lib / "b.fits", **_std_header(OBJECT="", **{"RA": 80.0, "DEC": 20.0}))
    await index.scan(lib)

    groups, total = await index.list_groups(ImageFilters(), page=1, page_size=50)
    assert total == 2


@pytest.mark.asyncio
async def test_coordinate_search_across_the_ra_seam(index: ViewerIndex, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    write_fits(lib / "a.fits", **_std_header(OBJECT="", **{"RA": 359.5, "DEC": 10.0}))
    write_fits(lib / "b.fits", **_std_header(OBJECT="", **{"RA": 0.5, "DEC": 10.0}))
    write_fits(lib / "c.fits", **_std_header(OBJECT="", **{"RA": 180.0, "DEC": 10.0}))
    await index.scan(lib)

    items, total = await index.list_images(
        ImageFilters(ra_deg=0.0, dec_deg=10.0, radius_deg=2.0), limit=50,
    )
    assert total == 2
    names = {Path(r.path).name for r in items}
    assert names == {"a.fits", "b.fits"}


@pytest.mark.asyncio
async def test_coordinate_search_near_the_pole_does_not_crash(index: ViewerIndex, tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    write_fits(lib / "a.fits", **_std_header(OBJECT="", **{"RA": 10.0, "DEC": 89.5}))
    write_fits(lib / "b.fits", **_std_header(OBJECT="", **{"RA": 200.0, "DEC": 89.5}))
    write_fits(lib / "c.fits", **_std_header(OBJECT="", **{"RA": 10.0, "DEC": 0.0}))
    await index.scan(lib)

    items, total = await index.list_images(
        ImageFilters(ra_deg=10.0, dec_deg=90.0, radius_deg=1.0), limit=50,
    )
    # Near the pole, any RA at a matching declination is a hit — both a and b qualify.
    assert total == 2


@pytest.mark.asyncio
async def test_purge_outside_removes_rows_from_the_old_root(index: ViewerIndex, tmp_path: Path) -> None:
    old_lib = tmp_path / "old_lib"
    new_lib = tmp_path / "new_lib"
    write_fits(old_lib / "a.fits", **_std_header())
    write_fits(new_lib / "b.fits", **_std_header())
    await index.scan(old_lib)
    await index.scan(new_lib)

    removed = await index.purge_outside(new_lib)

    assert removed == 1
    _, total = await index.list_images(ImageFilters(), limit=50)
    assert total == 1
