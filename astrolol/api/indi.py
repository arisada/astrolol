"""
INDI-specific API endpoints.

GET  /indi/drivers          — list all drivers from the catalog
GET  /indi/drivers/{kind}   — filter by device kind (camera, mount, focuser, …)
POST /indi/load_driver      — start indiserver, load a driver, return its property snapshot
"""
from __future__ import annotations

import asyncio

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
    # Actual device names announced by the driver.  Drivers like indi_asi_ccd
    # announce model-specific names ("ZWO CCD ASI294MC Pro") instead of the
    # catalog name ("ZWO CCD").  When multiple cameras are connected all names
    # are returned so the user can register each one with the correct name.
    device_names: list[str] = []


@router.post("/load_driver", response_model=LoadDriverResponse)
async def load_driver(body: LoadDriverRequest, request: Request) -> LoadDriverResponse:
    """Start indiserver (if managed), load a driver, and return its property snapshot.

    This is Phase 1 of two-phase connect.  The caller then configures any
    pre-connect properties and calls POST /devices/connect with pre_connect_props.

    The response includes ``device_names`` — the actual INDI device names announced
    by the driver.  For single-camera setups this is typically one entry; for
    multi-camera setups (e.g. 3 ZWO cameras) all camera names are returned so
    the user can register each one with the correct name.
    """
    manager = getattr(request.app.state.registry, "indi_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="INDI plugin not available.")

    logger.info("indi.load_driver_request", executable=body.executable, device=body.device_name)
    try:
        await manager.ensure_started()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to start indiserver: {exc}") from exc

    client = manager.client
    exact_name = body.device_name

    # t0 check: if the driver was already loaded (e.g. cameras announced at indiserver
    # startup before the user clicked "Load driver"), return whatever is already known.
    # This handles multi-camera setups where all devices appear seconds after indiserver
    # starts, long before the user interacts with the UI.
    existing = [d for d in client.list_devices() if d == exact_name or d.startswith(exact_name + " ")]
    if existing:
        logger.info(
            "indi.load_driver_already_announced",
            device=exact_name,
            found=existing,
        )
        device_names = existing
    else:
        # Driver not yet loaded — load it now and wait for devices to appear.
        try:
            if body.executable:
                await manager.load_driver(body.executable)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to start driver: {exc}") from exc

        known_before = set(client.list_devices())

        # Phase 1: try exact device name (handles single-camera setups)
        try:
            await client.wait_for_property(exact_name, "CONNECTION", timeout=15.0)
            # Exact match found — brief extra window to collect any additional cameras
            # from the same multi-camera driver that came up simultaneously
            await asyncio.sleep(1.0)
            device_names = [exact_name] + [
                d for d in client.list_devices()
                if d not in known_before and d != exact_name and d.startswith(exact_name)
            ]
        except TimeoutError:
            # Phase 2: prefix fallback.  Handles drivers that announce model-specific
            # names ("ZWO CCD ASI294MC Pro") instead of the generic catalog name
            # ("ZWO CCD").  Wait up to 5 s more (20 s total) for any matching device.
            logger.info(
                "indi.load_driver_prefix_fallback",
                device=exact_name,
                reason="exact name not announced; trying prefix match",
            )
            try:
                device_names = await client.wait_for_devices_by_prefix(
                    exact_name, known_before, timeout=5.0
                )
            except TimeoutError:
                raise HTTPException(
                    status_code=504,
                    detail=(
                        f"Driver loaded but no device starting with '{exact_name}' announced "
                        "properties within 20 s. Check that the driver is installed and the "
                        "device is connected."
                    ),
                )

    resolved = device_names[0]
    snapshot = await client.get_properties_snapshot(resolved)
    props = [prop_to_out(p) for p in snapshot.values()]
    result = [p for p in props if p is not None]
    result.sort(key=lambda x: (x.group, x.name))
    logger.info(
        "indi.load_driver_done",
        device=resolved,
        all_devices=device_names,
        num_props=len(result),
    )
    return LoadDriverResponse(properties=result, device_names=device_names)
