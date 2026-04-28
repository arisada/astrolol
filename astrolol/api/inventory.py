import zoneinfo
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import TypeAdapter

from astrolol.equipment.models import EquipmentItem
from astrolol.equipment.store import EquipmentStore

router = APIRouter(prefix="/inventory", tags=["inventory"])


def _system_timezone() -> str:
    """Best-effort read of the system timezone name."""
    try:
        tz_file = Path("/etc/timezone")
        if tz_file.exists():
            return tz_file.read_text().strip()
    except OSError:
        pass
    return "UTC"

_item_adapter: TypeAdapter[EquipmentItem] = TypeAdapter(EquipmentItem)


def _store(request: Request) -> EquipmentStore:
    return request.app.state.equipment_store


@router.get("/timezones")
async def list_timezones() -> dict:
    """Return sorted list of IANA timezone names and the system default."""
    zones = sorted(zoneinfo.available_timezones())
    return {"timezones": zones, "system_default": _system_timezone()}


@router.get("", response_model=list[EquipmentItem])
async def list_items(request: Request) -> list[EquipmentItem]:
    """Return all inventory items."""
    return _store(request).list()


@router.post("", response_model=EquipmentItem, status_code=201)
async def create_item(item: EquipmentItem, request: Request) -> EquipmentItem:
    """Add a new item to the inventory."""
    return _store(request).create(item)


@router.get("/{item_id}", response_model=EquipmentItem)
async def get_item(item_id: str, request: Request) -> EquipmentItem:
    try:
        return _store(request).get(item_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found.")


@router.put("/{item_id}", response_model=EquipmentItem)
async def update_item(item_id: str, item: EquipmentItem, request: Request) -> EquipmentItem:
    if item.id != item_id:  # type: ignore[union-attr]
        raise HTTPException(status_code=400, detail="Item id in URL and body must match.")
    try:
        return _store(request).update(item)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found.")


@router.delete("/{item_id}", status_code=204)
async def delete_item(item_id: str, request: Request) -> None:
    try:
        _store(request).delete(item_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Item '{item_id}' not found.")
