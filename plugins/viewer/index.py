"""ViewerIndex — the sqlite3-backed catalogue of FITS files under the library directory.

Single-writer discipline: one sqlite3 connection (``check_same_thread=False``, WAL mode)
guarded by one ``asyncio.Lock``, so no two coroutines ever touch it concurrently — sqlite3
connections aren't safe to hand between arbitrary threadpool threads, and this also gives
the rescan/live-indexer race its safety property for free (see ``scan`` below).

Blocking work (sqlite calls, ``astropy.io.fits.getheader``) always runs through
``asyncio.to_thread``, never directly on the event loop.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

import structlog

from plugins.viewer import coords, grouping
from plugins.viewer.models import Facets, GroupSummary, ImageRecord, RescanResult, RollupRow

logger = structlog.get_logger()

_EXTENSIONS = {".fits", ".fit", ".fts", ".fz"}
_EXCLUDED_DIR_NAMES = {"_rejected"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    id TEXT PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    size_bytes INTEGER NOT NULL,
    mtime REAL NOT NULL,
    captured_at TEXT NOT NULL,
    captured_at_estimated INTEGER NOT NULL,
    frame_type TEXT NOT NULL,
    object_name TEXT NOT NULL DEFAULT '',
    exposure_s REAL,
    gain INTEGER,
    binning INTEGER,
    filter_name TEXT NOT NULL DEFAULT '',
    camera_name TEXT NOT NULL DEFAULT '',
    telescope_name TEXT NOT NULL DEFAULT '',
    ra_deg REAL,
    dec_deg REAL,
    coord_source TEXT,
    ccd_temp REAL,
    width INTEGER,
    height INTEGER,
    night TEXT NOT NULL,
    sky_cell_ra REAL,
    sky_cell_dec REAL,
    bg_median REAL,
    star_count INTEGER,
    hfr REAL,
    group_key TEXT NOT NULL,
    scan_generation INTEGER NOT NULL,
    indexed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_night_object ON images(night, object_name);
CREATE INDEX IF NOT EXISTS idx_captured_at ON images(captured_at);
CREATE INDEX IF NOT EXISTS idx_coords ON images(dec_deg, ra_deg);
CREATE INDEX IF NOT EXISTS idx_frame_type ON images(frame_type);
CREATE INDEX IF NOT EXISTS idx_group_key ON images(group_key);
"""


class RescanInProgress(Exception):
    pass


@dataclass
class ImageFilters:
    frame_types: list[str] | None = None
    object_name: str | None = None       # exact match (group expansion)
    filter_name: str | None = None       # exact match
    camera_name: str | None = None       # exact match
    exposure_s: float | None = None      # exact match (already-rounded value)
    binning: int | None = None
    gain: int | None = None
    night: str | None = None
    sky_cell_ra: float | None = None
    sky_cell_dec: float | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    search: str | None = None            # substring match on object_name/path
    star_count_min: int | None = None
    star_count_max: int | None = None
    hfr_min: float | None = None
    hfr_max: float | None = None
    ra_deg: float | None = None          # proximity search
    dec_deg: float | None = None
    radius_deg: float | None = None

    def where(self) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if self.frame_types:
            clauses.append(f"frame_type IN ({','.join('?' * len(self.frame_types))})")
            params.extend(self.frame_types)
        if self.object_name is not None:
            clauses.append("object_name = ?")
            params.append(self.object_name)
        if self.filter_name is not None:
            clauses.append("filter_name = ?")
            params.append(self.filter_name)
        if self.camera_name is not None:
            clauses.append("camera_name = ?")
            params.append(self.camera_name)
        if self.exposure_s is not None:
            clauses.append("exposure_s = ?")
            params.append(self.exposure_s)
        if self.binning is not None:
            clauses.append("binning = ?")
            params.append(self.binning)
        if self.gain is not None:
            clauses.append("gain = ?")
            params.append(self.gain)
        if self.night is not None:
            clauses.append("night = ?")
            params.append(self.night)
        if self.sky_cell_ra is not None:
            clauses.append("sky_cell_ra = ?")
            params.append(self.sky_cell_ra)
        if self.sky_cell_dec is not None:
            clauses.append("sky_cell_dec = ?")
            params.append(self.sky_cell_dec)
        if self.date_from is not None:
            clauses.append("captured_at >= ?")
            params.append(self.date_from.isoformat())
        if self.date_to is not None:
            clauses.append("captured_at <= ?")
            params.append(self.date_to.isoformat())
        if self.search:
            clauses.append("(object_name LIKE ? OR path LIKE ?)")
            params.extend([f"%{self.search}%", f"%{self.search}%"])
        if self.star_count_min is not None:
            clauses.append("star_count >= ?")
            params.append(self.star_count_min)
        if self.star_count_max is not None:
            clauses.append("star_count <= ?")
            params.append(self.star_count_max)
        if self.hfr_min is not None:
            clauses.append("hfr >= ?")
            params.append(self.hfr_min)
        if self.hfr_max is not None:
            clauses.append("hfr <= ?")
            params.append(self.hfr_max)
        if self.ra_deg is not None and self.dec_deg is not None and self.radius_deg is not None:
            bb = _bounding_box(self.ra_deg, self.dec_deg, self.radius_deg)
            if bb is None:
                # Box spans the full RA range (near a pole) — only the dec bound applies.
                clauses.append("dec_deg BETWEEN ? AND ?")
                params.extend([self.dec_deg - self.radius_deg, self.dec_deg + self.radius_deg])
            else:
                ra_lo, ra_hi, dec_lo, dec_hi = bb
                clauses.append("dec_deg BETWEEN ? AND ?")
                params.extend([dec_lo, dec_hi])
                if ra_lo <= ra_hi:
                    clauses.append("ra_deg BETWEEN ? AND ?")
                    params.extend([ra_lo, ra_hi])
                else:
                    # Wraps across the 0/360 seam.
                    clauses.append("(ra_deg >= ? OR ra_deg <= ?)")
                    params.extend([ra_lo, ra_hi])

        where = " AND ".join(clauses) if clauses else "1=1"
        return where, params


def _bounding_box(ra_deg: float, dec_deg: float, radius_deg: float) -> tuple[float, float, float, float] | None:
    """RA/Dec bounding box for a proximity search. Returns None when the box would need
    to span the full 0-360 RA range (within radius_deg of a pole, where a fixed-width RA
    window is meaningless) — the caller then filters on dec alone."""
    dec_lo = dec_deg - radius_deg
    dec_hi = dec_deg + radius_deg
    if abs(dec_deg) + radius_deg >= 90.0:
        return None
    cos_dec = math.cos(math.radians(dec_deg))
    ra_width = radius_deg / cos_dec if cos_dec > 1e-6 else 180.0
    ra_lo = (ra_deg - ra_width) % 360.0
    ra_hi = (ra_deg + ra_width) % 360.0
    return ra_lo, ra_hi, dec_lo, dec_hi


def _map_frame_type(imagetyp: str | None) -> str:
    t = (imagetyp or "").lower()
    for ft in ("dark", "flat", "bias", "light"):
        if ft in t:
            return ft
    return "unknown"


def _parse_captured_at(header: dict, mtime: float) -> tuple[datetime, bool]:
    raw = header.get("DATE-OBS")
    if raw:
        try:
            text = str(raw).replace("Z", "+00:00")
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt, False
        except ValueError:
            pass
    return datetime.fromtimestamp(mtime, tz=timezone.utc), True


def _extract_record(path: Path, st: os.stat_result, generation: int) -> dict:
    from astropy.io import fits

    header = dict(fits.getheader(path))
    frame_type = _map_frame_type(header.get("IMAGETYP"))
    object_name = str(header.get("OBJECT", "") or "").strip()
    captured_at, estimated = _parse_captured_at(header, st.st_mtime)

    exposure_raw = header.get("EXPTIME", header.get("EXPOSURE"))
    exposure_s = grouping.round_exposure(float(exposure_raw)) if exposure_raw is not None else None
    gain_raw = header.get("GAIN")
    gain = grouping.round_gain(float(gain_raw)) if gain_raw is not None else None
    binning = header.get("XBINNING")
    binning = int(binning) if binning is not None else None
    filter_name = grouping.normalize_filter_name(header.get("FILTER"))
    camera_name = str(header.get("INSTRUME", "") or "").strip()
    telescope_name = str(header.get("TELESCOP", "") or "").strip()
    ccd_temp = header.get("CCD-TEMP")
    width = header.get("NAXIS1")
    height = header.get("NAXIS2")

    ra_deg, dec_deg, coord_source = coords.resolve_coords(header)

    sitelong = header.get("SITELONG")
    night = grouping.compute_night(captured_at, float(sitelong) if sitelong is not None else None)

    sky_cell_ra = sky_cell_dec = None
    if not object_name and ra_deg is not None and dec_deg is not None and frame_type == "light":
        sky_cell_dec, sky_cell_ra = grouping.sky_cell(ra_deg, dec_deg)

    group_key = grouping.compute_group_key(
        frame_type=frame_type, object_name=object_name, filter_name=filter_name,
        camera_name=camera_name, exposure_s=exposure_s, binning=binning, gain=gain,
        night=night, sky_cell_ra=sky_cell_ra, sky_cell_dec=sky_cell_dec,
    )

    return dict(
        id=hashlib.sha1(str(path).encode()).hexdigest(),
        path=str(path),
        size_bytes=st.st_size,
        mtime=st.st_mtime,
        captured_at=captured_at.isoformat(),
        captured_at_estimated=int(estimated),
        frame_type=frame_type,
        object_name=object_name,
        exposure_s=exposure_s,
        gain=gain,
        binning=binning,
        filter_name=filter_name,
        camera_name=camera_name,
        telescope_name=telescope_name,
        ra_deg=ra_deg,
        dec_deg=dec_deg,
        coord_source=coord_source,
        ccd_temp=float(ccd_temp) if ccd_temp is not None else None,
        width=int(width) if width is not None else None,
        height=int(height) if height is not None else None,
        night=night,
        sky_cell_ra=sky_cell_ra,
        sky_cell_dec=sky_cell_dec,
        group_key=group_key,
        scan_generation=generation,
        indexed_at=datetime.now(timezone.utc).isoformat(),
    )


def _walk(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDED_DIR_NAMES]
        for name in filenames:
            if Path(name).suffix.lower() in _EXTENSIONS:
                yield Path(dirpath) / name


_COLUMNS = [
    "id", "path", "size_bytes", "mtime", "captured_at", "captured_at_estimated",
    "frame_type", "object_name", "exposure_s", "gain", "binning", "filter_name",
    "camera_name", "telescope_name", "ra_deg", "dec_deg", "coord_source", "ccd_temp",
    "width", "height", "night", "bg_median", "star_count", "hfr", "indexed_at",
]


def _row_to_record(row: sqlite3.Row) -> ImageRecord:
    d = dict(row)
    d["captured_at_estimated"] = bool(d["captured_at_estimated"])
    return ImageRecord(**{k: d[k] for k in _COLUMNS})


class ViewerIndex:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()
        self._generation = 0
        self._rescan_task: asyncio.Task | None = None
        self._cancel_event = asyncio.Event()

    async def start(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        def _open() -> sqlite3.Connection:
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.commit()
            return conn

        self._conn = await asyncio.to_thread(_open)
        row = await self._run(lambda c: c.execute("SELECT MAX(scan_generation) AS g FROM images").fetchone())
        self._generation = (row["g"] or 0) if row is not None else 0

    async def close(self) -> None:
        if self._rescan_task is not None and not self._rescan_task.done():
            self._rescan_task.cancel()
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    @property
    def is_rescanning(self) -> bool:
        return self._rescan_task is not None and not self._rescan_task.done()

    async def _run(self, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        assert self._conn is not None, "ViewerIndex.start() was not called"
        async with self._lock:
            return await asyncio.to_thread(fn, self._conn)

    # --- Live incremental indexing ---

    async def index_file(self, path: Path) -> None:
        """Index (or re-index) a single file — used for the ExposureCompleted live hook."""
        if not path.exists():
            return
        st = await asyncio.to_thread(path.stat)
        record = await asyncio.to_thread(_extract_record, path, st, self._generation)
        await self._run(lambda c: _upsert(c, record))
        logger.info("viewer.image_indexed", path=str(path))

    async def remove_by_path(self, path: Path) -> bool:
        def _op(c: sqlite3.Connection) -> bool:
            cur = c.execute("DELETE FROM images WHERE path = ?", (str(path),))
            c.commit()
            return cur.rowcount > 0
        removed = await self._run(_op)
        if removed:
            logger.info("viewer.image_removed", path=str(path))
        return removed

    # --- Rescan ---

    def request_cancel(self) -> None:
        self._cancel_event.set()

    async def scan(self, library_dir: Path, on_progress: Callable[[int], None] | None = None) -> RescanResult:
        """Run a scan. Single-flight tracking (rejecting a second concurrent scan)
        lives in ``start_rescan``, not here — this method is also called directly
        by callers (tests, a first synchronous scan) that don't need that tracking,
        and it must not conflict with ``start_rescan`` having already recorded
        itself as the in-flight task by the time this coroutine's body starts."""
        self._cancel_event = asyncio.Event()
        t0 = time.monotonic()
        self._generation += 1
        generation = self._generation

        existing = await self._run(lambda c: {
            r["path"]: (r["size_bytes"], r["mtime"])
            for r in c.execute(
                "SELECT path, size_bytes, mtime FROM images WHERE path LIKE ?",
                (f"{library_dir}%",),
            )
        })

        added = updated = 0
        scanned = 0
        for fp in await asyncio.to_thread(lambda: list(_walk(library_dir))):
            if self._cancel_event.is_set():
                raise asyncio.CancelledError()
            scanned += 1
            try:
                st = await asyncio.to_thread(fp.stat)
            except OSError:
                continue
            key = str(fp)
            prev = existing.get(key)
            if prev is not None and prev == (st.st_size, st.st_mtime):
                await self._run(lambda c, k=key, g=generation: _touch_generation(c, k, g))
            else:
                try:
                    record = await asyncio.to_thread(_extract_record, fp, st, generation)
                except Exception as exc:
                    logger.warning("viewer.index_extract_failed", path=key, error=str(exc))
                    continue
                await self._run(lambda c, r=record: _upsert(c, r))
                if prev is None:
                    added += 1
                else:
                    updated += 1
            if on_progress is not None and scanned % 200 == 0:
                on_progress(scanned)

        removed = await self._run(lambda c: _delete_stale(c, str(library_dir), generation))
        return RescanResult(added=added, updated=updated, removed=removed, duration_s=time.monotonic() - t0)

    def start_rescan(
        self, library_dir: Path,
        on_progress: Callable[[int], None] | None = None,
    ) -> asyncio.Task:
        if self.is_rescanning:
            raise RescanInProgress()
        self._rescan_task = asyncio.create_task(self.scan(library_dir, on_progress))
        return self._rescan_task

    async def purge_outside(self, library_dir: Path) -> int:
        """Remove rows whose path no longer falls under *library_dir* (called after the
        setting changes) — does not touch thumbnails; callers should GC those separately
        against the surviving id set."""
        def _op(c: sqlite3.Connection) -> int:
            cur = c.execute("DELETE FROM images WHERE path NOT LIKE ?", (f"{library_dir}%",))
            c.commit()
            return cur.rowcount
        return await self._run(_op)

    # --- Reads ---

    async def get(self, image_id: str) -> ImageRecord | None:
        row = await self._run(lambda c: c.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone())
        return _row_to_record(row) if row is not None else None

    async def get_by_path(self, path: Path) -> ImageRecord | None:
        row = await self._run(lambda c: c.execute("SELECT * FROM images WHERE path = ?", (str(path),)).fetchone())
        return _row_to_record(row) if row is not None else None

    async def all_ids(self) -> set[str]:
        rows = await self._run(lambda c: c.execute("SELECT id FROM images").fetchall())
        return {r["id"] for r in rows}

    async def list_images(
        self, filters: ImageFilters, *, before_captured_at: str | None = None,
        before_id: str | None = None, limit: int = 50, ascending: bool = False,
    ) -> tuple[list[ImageRecord], int]:
        where, params = filters.where()

        def _op(c: sqlite3.Connection) -> tuple[list[ImageRecord], int]:
            total = c.execute(f"SELECT COUNT(*) AS n FROM images WHERE {where}", params).fetchone()["n"]
            order = "ASC" if ascending else "DESC"
            cursor_clause = ""
            cursor_params: list[Any] = []
            if before_captured_at is not None and before_id is not None:
                op = ">" if ascending else "<"
                cursor_clause = f" AND (captured_at {op} ? OR (captured_at = ? AND id {op} ?))"
                cursor_params = [before_captured_at, before_captured_at, before_id]
            rows = c.execute(
                f"SELECT * FROM images WHERE {where}{cursor_clause} "
                f"ORDER BY captured_at {order}, id {order} LIMIT ?",
                [*params, *cursor_params, limit],
            ).fetchall()
            return [_row_to_record(r) for r in rows], total

        return await self._run(_op)

    async def list_groups(
        self, filters: ImageFilters, *, page: int = 1, page_size: int = 50,
    ) -> tuple[list[GroupSummary], int]:
        where, params = filters.where()

        def _op(c: sqlite3.Connection) -> tuple[list[GroupSummary], int]:
            total = c.execute(
                f"SELECT COUNT(DISTINCT group_key) AS n FROM images WHERE {where}", params
            ).fetchone()["n"]
            rows = c.execute(
                f"""
                SELECT frame_type, object_name, filter_name, camera_name, exposure_s,
                       binning, gain, night, sky_cell_ra, sky_cell_dec,
                       COUNT(*) AS count, SUM(exposure_s) AS total_exposure_s,
                       MIN(captured_at) AS first_captured_at, MAX(captured_at) AS last_captured_at,
                       group_key
                FROM images
                WHERE {where}
                GROUP BY group_key
                ORDER BY MAX(captured_at) DESC
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
            groups = []
            for r in rows:
                rep = c.execute(
                    "SELECT id, ra_deg, dec_deg FROM images WHERE group_key = ? "
                    "ORDER BY captured_at ASC, id ASC LIMIT 1",
                    (r["group_key"],),
                ).fetchone()
                groups.append(GroupSummary(
                    frame_type=r["frame_type"], object_name=r["object_name"],
                    filter_name=r["filter_name"], camera_name=r["camera_name"],
                    exposure_s=r["exposure_s"], binning=r["binning"], gain=r["gain"],
                    night=r["night"], count=r["count"],
                    total_exposure_s=r["total_exposure_s"] or 0.0,
                    first_captured_at=r["first_captured_at"], last_captured_at=r["last_captured_at"],
                    representative_id=rep["id"] if rep else "",
                    ra_deg=rep["ra_deg"] if rep else None, dec_deg=rep["dec_deg"] if rep else None,
                    sky_cell_ra=r["sky_cell_ra"], sky_cell_dec=r["sky_cell_dec"],
                ))
            return groups, total

        return await self._run(_op)

    async def facets(self) -> Facets:
        def _op(c: sqlite3.Connection) -> Facets:
            def _distinct(col: str) -> list[str]:
                rows = c.execute(f"SELECT DISTINCT {col} AS v FROM images WHERE {col} != '' ORDER BY v").fetchall()
                return [r["v"] for r in rows]
            return Facets(
                objects=_distinct("object_name"),
                frame_types=_distinct("frame_type"),
                filters=_distinct("filter_name"),
                cameras=_distinct("camera_name"),
            )
        return await self._run(_op)

    async def rollup(self) -> list[RollupRow]:
        def _op(c: sqlite3.Connection) -> list[RollupRow]:
            rows = c.execute(
                """
                SELECT object_name, COUNT(*) AS frame_count, SUM(exposure_s) AS total_exposure_s,
                       COUNT(DISTINCT night) AS nights,
                       MIN(captured_at) AS first_captured_at, MAX(captured_at) AS last_captured_at
                FROM images
                WHERE frame_type = 'light' AND object_name != ''
                GROUP BY object_name
                ORDER BY total_exposure_s DESC
                """
            ).fetchall()
            return [RollupRow(
                object_name=r["object_name"], frame_count=r["frame_count"],
                total_exposure_s=r["total_exposure_s"] or 0.0, nights=r["nights"],
                first_captured_at=r["first_captured_at"], last_captured_at=r["last_captured_at"],
            ) for r in rows]
        return await self._run(_op)

    async def count_under(self, library_dir: Path) -> int:
        row = await self._run(lambda c: c.execute(
            "SELECT COUNT(*) AS n FROM images WHERE path LIKE ?", (f"{library_dir}%",)
        ).fetchone())
        return row["n"] if row is not None else 0

    async def update_quality(self, image_id: str, bg_median: float | None, star_count: int | None, hfr: float | None) -> None:
        def _op(c: sqlite3.Connection) -> None:
            c.execute(
                "UPDATE images SET bg_median = ?, star_count = ?, hfr = ? WHERE id = ?",
                (bg_median, star_count, hfr, image_id),
            )
            c.commit()
        await self._run(_op)

    async def light_frames_missing_quality(self, limit: int = 20) -> list[ImageRecord]:
        rows = await self._run(lambda c: c.execute(
            "SELECT * FROM images WHERE frame_type = 'light' AND star_count IS NULL LIMIT ?",
            (limit,),
        ).fetchall())
        return [_row_to_record(r) for r in rows]


def _upsert(conn: sqlite3.Connection, record: dict) -> None:
    cols = [
        "id", "path", "size_bytes", "mtime", "captured_at", "captured_at_estimated",
        "frame_type", "object_name", "exposure_s", "gain", "binning", "filter_name",
        "camera_name", "telescope_name", "ra_deg", "dec_deg", "coord_source", "ccd_temp",
        "width", "height", "night", "sky_cell_ra", "sky_cell_dec", "group_key",
        "scan_generation", "indexed_at",
    ]
    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "id")
    conn.execute(
        f"INSERT INTO images ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        [record[c] for c in cols],
    )
    conn.commit()


def _touch_generation(conn: sqlite3.Connection, path: str, generation: int) -> None:
    conn.execute("UPDATE images SET scan_generation = ? WHERE path = ?", (generation, path))
    conn.commit()


def _delete_stale(conn: sqlite3.Connection, library_dir_prefix: str, generation: int) -> int:
    cur = conn.execute(
        "DELETE FROM images WHERE path LIKE ? AND scan_generation < ?",
        (f"{library_dir_prefix}%", generation),
    )
    conn.commit()
    return cur.rowcount
