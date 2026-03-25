"""
INDI-specific API endpoints.

GET /indi/drivers          — list all drivers from the catalog
GET /indi/drivers/{kind}   — filter by device kind (camera, mount, focuser, …)
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from astrolol.devices.indi.catalog import DriverEntry, load_catalog

router = APIRouter(prefix="/indi", tags=["indi"])


class DriverEntryOut(BaseModel):
    label: str
    executable: str
    device_name: str
    group: str
    kind: str
    manufacturer: str

    @classmethod
    def from_entry(cls, e: DriverEntry) -> "DriverEntryOut":
        return cls(
            label=e.label,
            executable=e.executable,
            device_name=e.device_name,
            group=e.group,
            kind=e.kind,
            manufacturer=e.manufacturer,
        )


@router.get("/drivers", response_model=list[DriverEntryOut])
def list_drivers() -> list[DriverEntryOut]:
    """Return every driver in the INDI catalog."""
    return [DriverEntryOut.from_entry(e) for e in load_catalog()]


@router.get("/drivers/{kind}", response_model=list[DriverEntryOut])
def list_drivers_by_kind(kind: str) -> list[DriverEntryOut]:
    """Return catalog entries for a specific device kind."""
    return [DriverEntryOut.from_entry(e) for e in load_catalog() if e.kind == kind]
