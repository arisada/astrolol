"""
INDI-specific API endpoints.

GET  /indi/drivers          — list all drivers from the catalog
GET  /indi/drivers/{kind}   — filter by device kind (camera, mount, focuser, …)
POST /indi/load_driver      — start indiserver, load a driver, return its property snapshot
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from astrolol.api.properties import PropertyOut, prop_to_out
from astrolol.devices.indi.catalog import DriverEntry, load_catalog

logger = structlog.get_logger()

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


# ---------------------------------------------------------------------------
# Two-phase connect: Phase 1 — load driver and return property snapshot
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Device messages
# ---------------------------------------------------------------------------

class DeviceMessage(BaseModel):
    timestamp: str
    message: str


@router.get("/messages/{device_name}", response_model=list[DeviceMessage])
async def get_device_messages(device_name: str, request: Request) -> list[DeviceMessage]:
    """Return the last 8 messages emitted by an INDI device driver."""
    manager = getattr(request.app.state.registry, "indi_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="INDI plugin not available.")
    raw = manager.client.get_messages(device_name)
    return [DeviceMessage(**m) for m in raw]


# ---------------------------------------------------------------------------
# Two-phase connect: Phase 1 — load driver and return property snapshot
# ---------------------------------------------------------------------------

class LoadDriverRequest(BaseModel):
    executable: str
    device_name: str


class LoadDriverResponse(BaseModel):
    properties: list[PropertyOut]


@router.post("/load_driver", response_model=LoadDriverResponse)
async def load_driver(body: LoadDriverRequest, request: Request) -> LoadDriverResponse:
    """Start indiserver (if managed), load a driver, and return its property snapshot.

    This is Phase 1 of two-phase connect.  The caller then configures any
    pre-connect properties and calls POST /devices/connect with pre_connect_props.
    """
    manager = getattr(request.app.state.registry, "indi_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="INDI plugin not available.")

    logger.info("indi.load_driver_request", executable=body.executable, device=body.device_name)
    try:
        await manager.ensure_started()
        if body.executable:
            await manager.load_driver(body.executable)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to start driver: {exc}") from exc

    client = manager.client
    try:
        await client.wait_for_property(body.device_name, "CONNECTION", timeout=15.0)
    except TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=(
                f"Driver loaded but device '{body.device_name}' did not announce properties "
                "within 15 s. Check that the device name matches the driver exactly."
            ),
        )

    snapshot = await client.get_properties_snapshot(body.device_name)
    props = [prop_to_out(p) for p in snapshot.values()]
    result = [p for p in props if p is not None]
    result.sort(key=lambda x: (x.group, x.name))
    logger.info("indi.load_driver_done", device=body.device_name, num_props=len(result))
    return LoadDriverResponse(properties=result)
