"""
INDI-specific API endpoints.

GET  /indi/server           — which server (indiserver or INDIGO), managed or not, where
GET  /indi/drivers          — list all drivers from the catalog
GET  /indi/drivers/{kind}   — filter by device kind (camera, mount, focuser, …)
POST /indi/load_driver      — start the server, load a driver, return its property snapshot

The server is indiserver or an INDIGO server (Settings.indi_server_kind); the catalog and
the way a loaded driver's devices are found follow it.
"""
from __future__ import annotations

import asyncio

import structlog
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from astrolol.api.properties import PropertyOut, prop_to_out
from astrolol.config.settings import settings
from astrolol.devices.indi import indigo
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


class IndiServerChoiceOut(BaseModel):
    kind: Literal["indi", "indigo"]
    managed: bool
    host: str
    port: int
    indigo_path: str                  # the INDIGO server program


class IndiServerInfo(BaseModel):
    kind: Literal["indi", "indigo"]   # indiserver or an INDIGO server
    managed: bool                     # astrolol starts it
    host: str
    port: int
    # The server used from the next start (Options' choice, UserSettings.indi_server), the
    # parts of it the start-up configuration fixes (file or environment), and whether it
    # differs from the running one.
    next: IndiServerChoiceOut
    env: list[str] = []
    restart_needed: bool = False


@router.get("/server", response_model=IndiServerInfo)
def get_server(request: Request) -> IndiServerInfo:
    """Which server astrolol talks INDI to, and how; and the one chosen for the next start."""
    from astrolol.config.settings import CONFIGURED_FIELDS, INDI_SERVER_FIELDS, indi_server_configured_keys

    manager = getattr(request.app.state.registry, "indi_manager", None)
    server = getattr(manager, "_server", None)
    # settings hold what this run started with (the choice is applied once, at start).
    running = {key: getattr(settings, field) for key, field in INDI_SERVER_FIELDS.items()}
    choice = request.app.state.profile_store.get_user_settings().indi_server
    nxt = {
        key: value if field in CONFIGURED_FIELDS or getattr(choice, key) is None else getattr(choice, key)
        for (key, field), value in zip(INDI_SERVER_FIELDS.items(), running.values())
    }
    # The INDIGO program only matters to a managed INDIGO server; the host only to an external one.
    relevant = ["kind", "managed", "port"]
    if not nxt["managed"]:
        relevant.append("host")
    if nxt["kind"] == "indigo" and nxt["managed"]:
        relevant.append("indigo_path")
    return IndiServerInfo(
        kind=getattr(manager, "server_kind", settings.indi_server_kind),
        managed=getattr(server, "manage", settings.indi_manage_server),
        host=getattr(server, "host", settings.indi_host),
        port=getattr(server, "port", settings.indi_port),
        next=IndiServerChoiceOut(**nxt),
        env=indi_server_configured_keys(),
        restart_needed=any(nxt[k] != running[k] for k in relevant),
    )


def _catalog(request: Request) -> list[DriverEntry]:
    manager = getattr(request.app.state.registry, "indi_manager", None)
    if getattr(manager, "server_kind", "indi") != "indigo":
        return load_catalog()
    entries = indigo.load_catalog(indigo.catalog_dirs(settings.indigo_server_path))
    if not entries and manager is not None:
        # No driver list on this machine (a remote server): the server's own, once connected.
        entries = indigo.catalog_from_server(manager.client)
    return entries


@router.get("/drivers", response_model=list[DriverEntryOut])
def list_drivers(request: Request) -> list[DriverEntryOut]:
    """Return every driver in the catalog."""
    return [DriverEntryOut.from_entry(e) for e in _catalog(request)]


@router.get("/drivers/{kind}", response_model=list[DriverEntryOut])
def list_drivers_by_kind(kind: str, request: Request) -> list[DriverEntryOut]:
    """Return catalog entries for a specific device kind."""
    return [DriverEntryOut.from_entry(e) for e in _catalog(request) if e.kind == kind]


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

class DebugLevelRequest(BaseModel):
    level: int  # 0=off, 1=tags only, 2=full XML


@router.post("/debug", status_code=204)
async def set_debug_level(body: DebugLevelRequest, request: Request) -> None:
    """Set INDI protocol debug verbosity (0=off, 1=tags, 2=full XML)."""
    manager = getattr(request.app.state.registry, "indi_manager", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="INDI plugin not available.")
    manager.client.set_debug_level(body.level)


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
    # Properties shown but not offered: they set up the server, not the device (INDIGO's).
    disabled_properties: list[str] = []


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

    if getattr(manager, "server_kind", "indi") == "indigo":
        device_names = await _load_indigo_driver(manager, body.executable)
        response = await _snapshot_response(client, device_names)
        response.disabled_properties = sorted(
            p.name for p in response.properties if p.name in indigo.SERVER_ONLY_PROPERTIES
        )
        return response

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
                await manager.preload_driver(body.executable)
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

    return await _snapshot_response(client, device_names)


async def _snapshot_response(client, device_names: list[str]) -> LoadDriverResponse:  # noqa: ANN001
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


async def _load_indigo_driver(manager, executable: str) -> list[str]:  # noqa: ANN001
    """Load an INDIGO driver and return its devices of the driver's kind.

    INDIGO device names are the driver's choice ("ZWO ASI294MC Pro #0"), so its devices are
    found by the driver they report (DRIVER_INFO.DEVICE_DRIVER), not by name.
    """
    client = manager.client
    if not executable:
        raise HTTPException(status_code=422, detail="An INDIGO driver name is required.")
    devices = indigo.devices_of_driver(client, executable)
    if not devices:
        try:
            await manager.preload_driver(executable)
        except (ValueError, RuntimeError, TimeoutError) as exc:
            raise HTTPException(status_code=502, detail=f"Failed to start driver: {exc}") from exc
        try:
            await client._wait_cond(lambda: bool(indigo.devices_of_driver(client, executable)), timeout=20.0)
        except TimeoutError:
            raise HTTPException(
                status_code=504,
                detail=(
                    f"{executable} loaded but announced no device within 20 s. "
                    "Check that the device is plugged in and powered."
                ),
            )
        # A driver attaches its devices one after the other: a moment for the rest.
        await asyncio.sleep(1.0)
        devices = indigo.devices_of_driver(client, executable)
    return indigo.devices_for_kind(client, devices, indigo.kind_of_driver(executable))
