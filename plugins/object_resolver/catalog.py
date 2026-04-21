"""OpenNGC catalog: download, SQLite storage, name search, cone search."""
from __future__ import annotations

import asyncio
import csv
import io
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

OPENGC_URL = (
    "https://github.com/mattiaverga/OpenNGC/raw/refs/heads/master/database_files/NGC.csv"
)

_SKIP_TYPES = {"NonEx", "Dup"}

_TYPE_LABELS: dict[str, str] = {
    "G": "Galaxy",
    "GGroup": "Galaxy Group",
    "GPair": "Galaxy Pair",
    "GTrpl": "Galaxy Triple",
    "GClust": "Galaxy Cluster",
    "OC": "Open Cluster",
    "GC": "Globular Cluster",
    "PN": "Planetary Nebula",
    "HII": "HII Region",
    "EN": "Emission Nebula",
    "RN": "Reflection Nebula",
    "SNR": "Supernova Remnant",
    "Nova": "Nova",
    "Other": "Other",
    "*": "Star",
    "**": "Double Star",
    "*Ass": "Stellar Association",
    "Cl+N": "Cluster + Nebula",
}


def _parse_ra(s: str) -> float:
    """HH:MM:SS.ss → decimal degrees."""
    h, m, sec = s.split(":")
    return (float(h) + float(m) / 60.0 + float(sec) / 3600.0) * 15.0


def _parse_dec(s: str) -> float:
    """±DD:MM:SS.s → decimal degrees."""
    neg = s.startswith("-")
    d, m, sec = s.lstrip("+-").split(":")
    val = float(d) + float(m) / 60.0 + float(sec) / 3600.0
    return -val if neg else val


def _normalize_name(raw: str) -> str:
    """NGC0224 → 'NGC 224', IC0001 → 'IC 1'.

    Some OpenNGC rows have suffixes like 'IC 0080 NED01' (space-separated
    component tag) or 'IC 0186A' (letter suffix).  We extract only the
    leading digits so they resolve to the canonical name.
    """
    if raw.startswith("NGC"):
        m = re.match(r'(\d+)', raw[3:].strip())
        return f"NGC {int(m.group(1))}" if m else raw
    if raw.startswith("IC"):
        m = re.match(r'(\d+)', raw[2:].strip())
        return f"IC {int(m.group(1))}" if m else raw
    return raw


def _angular_sep_deg(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Great-circle angular separation in degrees (haversine)."""
    ra1r, dec1r, ra2r, dec2r = map(math.radians, (ra1, dec1, ra2, dec2))
    dra = ra2r - ra1r
    ddec = dec2r - dec1r
    a = (
        math.sin(ddec / 2) ** 2
        + math.cos(dec1r) * math.cos(dec2r) * math.sin(dra / 2) ** 2
    )
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(a))))


class ObjectCatalog:
    """Local OpenNGC SQLite catalog with name search and cone search."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._sync_lock = asyncio.Lock()

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def open(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _init_schema(self) -> None:
        assert self._conn is not None
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS catalog_meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS objects (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                primary_name TEXT NOT NULL UNIQUE,
                object_type  TEXT NOT NULL DEFAULT '',
                ra           REAL NOT NULL,
                dec          REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS object_names (
                name      TEXT NOT NULL COLLATE NOCASE,
                object_id INTEGER NOT NULL REFERENCES objects(id),
                PRIMARY KEY (name)
            );
            CREATE INDEX IF NOT EXISTS idx_objects_coords ON objects (ra, dec);
        """)
        self._conn.commit()

    # ── Status ─────────────────────────────────────────────────────────────────

    def is_populated(self) -> bool:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT value FROM catalog_meta WHERE key='object_count'"
        ).fetchone()
        return row is not None and int(row["value"]) > 0

    def object_count(self) -> int:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT value FROM catalog_meta WHERE key='object_count'"
        ).fetchone()
        return int(row["value"]) if row else 0

    def last_updated(self) -> str | None:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT value FROM catalog_meta WHERE key='last_updated'"
        ).fetchone()
        return row["value"] if row else None

    # ── Sync ───────────────────────────────────────────────────────────────────

    async def sync(self) -> int:
        """Download OpenNGC and (re)populate the database. Returns object count."""
        async with self._sync_lock:
            logger.info("object_resolver.sync_start", url=OPENGC_URL)
            content = await self._download_csv()
            count = await asyncio.to_thread(self._load_csv, content)
            logger.info("object_resolver.sync_done", count=count)
            return count

    async def _download_csv(self) -> str:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            resp = await client.get(OPENGC_URL)
            resp.raise_for_status()
            return resp.text

    def load_csv(self, content: str) -> int:
        """Parse OpenNGC CSV content and populate the database (public for testing)."""
        return self._load_csv(content)

    def _load_csv(self, content: str) -> int:
        assert self._conn is not None
        reader = csv.DictReader(io.StringIO(content), delimiter=";")
        count = 0

        self._conn.execute("DELETE FROM object_names")
        self._conn.execute("DELETE FROM objects")

        for row in reader:
            obj_type = (row.get("Type") or "").strip()
            if obj_type in _SKIP_TYPES:
                continue

            ra_str = (row.get("RA") or "").strip()
            dec_str = (row.get("Dec") or "").strip()
            if not ra_str or not dec_str:
                continue

            try:
                ra = _parse_ra(ra_str)
                dec = _parse_dec(dec_str)
            except (ValueError, AttributeError):
                continue

            raw_name = (row.get("Name") or "").strip()
            primary_name = _normalize_name(raw_name)
            type_label = _TYPE_LABELS.get(obj_type, obj_type)

            self._conn.execute(
                "INSERT OR REPLACE INTO objects (primary_name, object_type, ra, dec)"
                " VALUES (?, ?, ?, ?)",
                (primary_name, type_label, ra, dec),
            )
            obj_id = self._conn.execute(
                "SELECT id FROM objects WHERE primary_name=?", (primary_name,)
            ).fetchone()["id"]

            # Build the full set of aliases for this object
            aliases: set[str] = {primary_name, raw_name}

            if raw_name.startswith("NGC"):
                m = re.match(r'(\d+)', raw_name[3:].strip())
                if m:
                    n = int(m.group(1))
                    aliases.update({f"NGC {n}", f"NGC{n}"})
            elif raw_name.startswith("IC"):
                m = re.match(r'(\d+)', raw_name[2:].strip())
                if m:
                    n = int(m.group(1))
                    aliases.update({f"IC {n}", f"IC{n}"})

            messier = (row.get("M") or "").strip()
            if messier:
                m = int(messier)
                aliases.update({f"M {m}", f"M{m}", f"Messier {m}", f"Messier{m}"})

            common = (row.get("Common names") or "").strip()
            if common:
                aliases.update(n.strip() for n in common.split(",") if n.strip())

            identifiers = (row.get("Identifiers") or "").strip()
            if identifiers:
                aliases.update(i.strip() for i in identifiers.split(",") if i.strip())

            for alias in aliases:
                if alias:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO object_names (name, object_id) VALUES (?, ?)",
                        (alias, obj_id),
                    )

            count += 1

        self._conn.execute(
            "INSERT OR REPLACE INTO catalog_meta (key, value) VALUES ('object_count', ?)",
            (str(count),),
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO catalog_meta (key, value) VALUES ('last_updated', ?)",
            (datetime.now(timezone.utc).isoformat(),),
        )
        self._conn.commit()
        return count

    # ── Queries ────────────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search by name or alias (case-insensitive substring match)."""
        assert self._conn is not None
        rows = self._conn.execute(
            """
            SELECT DISTINCT o.id, o.primary_name, o.object_type, o.ra, o.dec
            FROM object_names n
            JOIN objects o ON o.id = n.object_id
            WHERE n.name LIKE ?
            LIMIT ?
            """,
            (f"%{query}%", limit),
        ).fetchall()
        return [self._enrich(row) for row in rows]

    def cone_search(
        self, ra: float, dec: float, radius_arcmin: float
    ) -> list[dict[str, Any]]:
        """Return objects within *radius_arcmin* of (ra, dec), sorted by distance."""
        assert self._conn is not None
        radius_deg = radius_arcmin / 60.0
        cos_dec = math.cos(math.radians(dec)) or 1e-9
        ra_margin = radius_deg / cos_dec

        rows = self._conn.execute(
            """
            SELECT id, primary_name, object_type, ra, dec
            FROM objects
            WHERE dec BETWEEN ? AND ?
              AND ra BETWEEN ? AND ?
            """,
            (
                dec - radius_deg,
                dec + radius_deg,
                ra - ra_margin,
                ra + ra_margin,
            ),
        ).fetchall()

        results = []
        for row in rows:
            sep_arcmin = _angular_sep_deg(ra, dec, row["ra"], row["dec"]) * 60.0
            if sep_arcmin <= radius_arcmin:
                d = self._enrich(row)
                d["distance_arcmin"] = round(sep_arcmin, 3)
                results.append(d)

        results.sort(key=lambda x: x["distance_arcmin"])
        return results

    def _enrich(self, row: sqlite3.Row) -> dict[str, Any]:
        """Attach all known aliases to a result row."""
        assert self._conn is not None
        aliases = [
            r["name"]
            for r in self._conn.execute(
                "SELECT name FROM object_names WHERE object_id=?", (row["id"],)
            ).fetchall()
            if r["name"] != row["primary_name"]
        ]
        return {
            "name": row["primary_name"],
            "aliases": sorted(aliases),
            "type": row["object_type"],
            "ra": row["ra"],
            "dec": row["dec"],
        }
