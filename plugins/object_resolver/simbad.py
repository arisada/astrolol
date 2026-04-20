"""Optional online fallback: CDS Sesame name resolver (wraps Simbad + NED)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

import httpx
import structlog

logger = structlog.get_logger()

_SESAME_URL = "https://cdsweb.u-strasbg.fr/cgi-bin/nph-sesame/-oxp/SN"


async def resolve(name: str) -> dict[str, Any] | None:
    """Query Sesame for *name*. Returns an object dict or None if not found."""
    url = f"{_SESAME_URL}?{quote(name)}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except Exception as exc:
        logger.warning("object_resolver.simbad_error", name=name, error=str(exc))
        return None

    try:
        root = ET.fromstring(resp.text)
        resolver = root.find(".//Resolver")
        if resolver is None:
            return None
        ra_el = resolver.find("jradeg")
        dec_el = resolver.find("jdedeg")
        if ra_el is None or dec_el is None or not ra_el.text or not dec_el.text:
            return None
        otype_el = resolver.find("otype")
        return {
            "name": name,
            "aliases": [],
            "type": (otype_el.text or "Unknown") if otype_el is not None else "Unknown",
            "ra": float(ra_el.text),
            "dec": float(dec_el.text),
            "source": "simbad",
        }
    except Exception as exc:
        logger.warning("object_resolver.simbad_parse_error", name=name, error=str(exc))
        return None
