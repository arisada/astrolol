"""
Parse the INDI driver catalog from /usr/share/indi/*.xml.

Each XML file describes a family of drivers. Example entry:

  <devGroup group="CCDs">
    <device label="ZWO CCD" manufacturer="ZWO">
      <driver name="ZWO CCD">indi_asi_ccd</driver>
      <version>2.1</version>
    </device>
  </devGroup>

The catalog maps INDI group names to our device kinds.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger()

CATALOG_DIR = Path("/usr/share/indi")

# INDI group → our DeviceKind
GROUP_TO_KIND: dict[str, str] = {
    "CCDs": "camera",
    "DSLRs": "camera",
    "Telescopes": "mount",
    "Focusers": "focuser",
    "Filter Wheels": "filter_wheel",
    "Aux": "aux",
}


@dataclass
class DriverEntry:
    label: str         # "ZWO CCD"          — shown to the user
    executable: str    # "indi_asi_ccd"      — loaded via FIFO / CLI
    device_name: str   # "ZWO CCD"           — INDI device name on the bus
    group: str         # "CCDs"              — INDI group
    kind: str          # "camera"            — our DeviceKind
    manufacturer: str  # "ZWO"


def load_catalog(catalog_dir: Path = CATALOG_DIR) -> list[DriverEntry]:
    """
    Parse all *.xml files in catalog_dir and return a flat list of drivers.
    Returns an empty list if the directory does not exist (INDI not installed).
    """
    if not catalog_dir.exists():
        logger.warning("indi.catalog_not_found", path=str(catalog_dir))
        return []

    entries: list[DriverEntry] = []
    for xml_file in sorted(catalog_dir.glob("*.xml")):
        try:
            entries.extend(_parse_file(xml_file))
        except ET.ParseError as exc:
            logger.warning("indi.catalog_parse_error", file=str(xml_file), error=str(exc))

    logger.info("indi.catalog_loaded", drivers=len(entries))
    return entries


def _parse_file(path: Path) -> list[DriverEntry]:
    tree = ET.parse(path)
    root = tree.getroot()
    entries: list[DriverEntry] = []

    for group_el in root.iter("devGroup"):
        group = group_el.get("group", "")
        kind = GROUP_TO_KIND.get(group, "aux")

        for device_el in group_el.iter("device"):
            label = device_el.get("label", "")
            manufacturer = device_el.get("manufacturer", "")
            driver_el = device_el.find("driver")
            if driver_el is None or not driver_el.text:
                continue

            entries.append(DriverEntry(
                label=label,
                executable=driver_el.text.strip(),
                device_name=driver_el.get("name", label),
                group=group,
                kind=kind,
                manufacturer=manufacturer,
            ))

    return entries


def drivers_by_kind(kind: str, catalog_dir: Path = CATALOG_DIR) -> list[DriverEntry]:
    return [d for d in load_catalog(catalog_dir) if d.kind == kind]
