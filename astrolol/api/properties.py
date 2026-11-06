"""
GET  /devices/{device_id}/properties        — snapshot of all live INDI properties
POST /devices/{device_id}/properties/{prop} — set a number, switch, or text property
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from astrolol.devices.indi import pins as pinlib
from astrolol.equipment.optical_path import find_item_for_entry

router = APIRouter(prefix="/devices", tags=["properties"])

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class PropertyWidget(BaseModel):
    name: str
    label: str
    value: float | str | bool | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    # used for light widgets: "idle" | "ok" | "busy" | "alert"
    state: str | None = None


class PropertyOut(BaseModel):
    name: str
    label: str
    group: str
    # "number" | "switch" | "text" | "light" | "blob"
    type: str
    # "idle" | "ok" | "busy" | "alert"
    state: str
    # "ro" | "rw" | "wo"
    permission: str
    # "1ofmany" | "atmost1" | "nofmany" — only for switches
    switch_rule: str | None = None
    widgets: list[PropertyWidget]
    # Whether its value can be kept (pinned) so that it is set again at every connection,
    # and whether it is. Only filled in by GET /devices/{device_id}/properties.
    pinnable: bool = False
    pinned: bool = False


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class SetPropertyRequest(BaseModel):
    # For number/text: element_name → value
    values: dict[str, float | str] | None = None
    # For switch: names of elements to turn ON (others turned off)
    on_elements: list[str] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STATE = {"Idle": "idle", "Ok": "ok", "Busy": "busy", "Alert": "alert"}
_ISR = {"OneOfMany": "1ofmany", "AtMostOne": "atmost1", "AnyOfMany": "nofmany"}


def prop_to_out(p: Any) -> PropertyOut | None:
    """Convert an indipyclient PropertyVector to PropertyOut. Returns None for BLOBs."""
    vtype = p.vectortype  # 'SwitchVector' | 'NumberVector' | 'TextVector' | 'LightVector' | 'BLOBVector'
    name = p.name
    label = p.label or name
    group = p.group or ""
    state = _STATE.get(p.state, "idle")
    perm = p.perm or "ro"

    if vtype == "NumberVector":
        widgets = [
            PropertyWidget(
                name=m.name,
                label=m.label or m.name,
                value=m.getfloatvalue(),
                min=float(m.min),
                max=float(m.max),
                step=float(m.step),
            )
            for m in p.data.values()
        ]
        return PropertyOut(name=name, label=label, group=group, type="number",
                           state=state, permission=perm, widgets=widgets)

    if vtype == "SwitchVector":
        rule = _ISR.get(p.rule or "", "1ofmany")
        widgets = [
            PropertyWidget(
                name=m.name,
                label=m.label or m.name,
                value=(m.membervalue == "On"),
            )
            for m in p.data.values()
        ]
        return PropertyOut(name=name, label=label, group=group, type="switch",
                           state=state, permission=perm, switch_rule=rule,
                           widgets=widgets)

    if vtype == "TextVector":
        widgets = [
            PropertyWidget(
                name=m.name,
                label=m.label or m.name,
                value=m.membervalue or "",
            )
            for m in p.data.values()
        ]
        return PropertyOut(name=name, label=label, group=group, type="text",
                           state=state, permission=perm, widgets=widgets)

    if vtype == "LightVector":
        widgets = [
            PropertyWidget(
                name=m.name,
                label=m.label or m.name,
                state=_STATE.get(m.membervalue, "idle"),
            )
            for m in p.data.values()
        ]
        return PropertyOut(name=name, label=label, group=group, type="light",
                           state=state, permission="ro", widgets=widgets)

    return None  # BLOBVector or unknown


def _resolve_indi_name(device_id: str, request: Request) -> str:
    """Look up the INDI device_name from the astrolol device_id."""
    device_manager = request.app.state.device_manager
    entry = device_manager._devices.get(device_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No connected device '{device_id}'.")
    indi_name: str = entry.config.params.get("device_name", "")
    if not indi_name:
        raise HTTPException(status_code=400, detail="Device has no INDI device_name parameter.")
    return indi_name


def _get_indi_client(request: Request):
    client = request.app.state.registry.indi_client
    if client is None:
        raise HTTPException(status_code=503, detail="INDI client not connected.")
    return client


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

def _item_and_pins(request: Request, device_id: str):  # noqa: ANN202
    """(the device's inventory item or None, the pins it holds)."""
    entry = request.app.state.device_manager._devices.get(device_id)
    store = getattr(request.app.state, "equipment_store", None)
    if entry is None or store is None:
        return None, {}
    item = find_item_for_entry(request.app.state.device_manager, store, entry)
    pins = pinlib.clean_pins((getattr(item, "connect_params", None) or {}).get(pinlib.PINNED_KEY)) if item else {}
    return item, pins


def _store_pins(request: Request, device_id: str, item, pins: dict) -> None:  # noqa: ANN001
    """Keep *pins* with the inventory item, and on the live device for its next reconnection."""
    params = {k: v for k, v in (item.connect_params or {}).items() if k != pinlib.PINNED_KEY}
    if pins:
        params[pinlib.PINNED_KEY] = pins
    request.app.state.equipment_store.update(item.model_copy(update={"connect_params": params}))
    entry = request.app.state.device_manager._devices[device_id]
    if pins:
        entry.config.params[pinlib.PINNED_KEY] = pins
    else:
        entry.config.params.pop(pinlib.PINNED_KEY, None)


@router.get("/{device_id}/properties", response_model=list[PropertyOut])
async def get_properties(device_id: str, request: Request) -> list[PropertyOut]:
    """Return a live snapshot of all INDI properties for a connected device."""
    client = _get_indi_client(request)
    indi_name = _resolve_indi_name(device_id, request)
    snapshot = await client.get_properties_snapshot(indi_name)
    item, pins = _item_and_pins(request, device_id)
    props = [prop_to_out(p) for p in snapshot.values()]
    result = [p for p in props if p is not None]
    for p in result:
        p.pinnable = item is not None and pinlib.pinnable(p.name, p.type, p.permission, p.switch_rule)
        p.pinned = p.name in pins
    result.sort(key=lambda x: (x.group, x.name))
    return result


@router.put("/{device_id}/pins/{prop_name}", response_model=dict)
async def pin_property(device_id: str, prop_name: str, request: Request) -> dict:
    """Keep the property's current value: it is set again every time the device connects."""
    client = _get_indi_client(request)
    indi_name = _resolve_indi_name(device_id, request)
    item, pins = _item_and_pins(request, device_id)
    if item is None:
        raise HTTPException(status_code=409, detail="This device is not in the equipment inventory: add it there first.")
    snapshot = await client.get_properties_snapshot(indi_name)
    raw = snapshot.get(prop_name)
    out = prop_to_out(raw) if raw is not None else None
    if out is None:
        raise HTTPException(status_code=404, detail=f"The device has no property '{prop_name}'.")
    if not pinlib.pinnable(out.name, out.type, out.permission, out.switch_rule):
        raise HTTPException(status_code=409, detail=f"'{prop_name}' cannot be pinned.")
    spec = pinlib.pin_spec(out.type, {w.name: w.value for w in out.widgets})
    if spec is None:
        raise HTTPException(status_code=409, detail=f"'{prop_name}' has no value to keep.")
    _store_pins(request, device_id, item, {**pins, prop_name: spec})
    return spec


@router.delete("/{device_id}/pins/{prop_name}", status_code=204, response_model=None)
async def unpin_property(device_id: str, prop_name: str, request: Request) -> None:
    """Stop keeping the property's value."""
    item, pins = _item_and_pins(request, device_id)
    if item is not None and prop_name in pins:
        _store_pins(request, device_id, item, {k: v for k, v in pins.items() if k != prop_name})


@router.post("/{device_id}/properties/{prop_name}", status_code=204, response_model=None)
async def set_property(
    device_id: str, prop_name: str, body: SetPropertyRequest, request: Request
) -> None:
    """Set a number, switch, or text INDI property on a connected device."""
    client = _get_indi_client(request)
    indi_name = _resolve_indi_name(device_id, request)
    try:
        if body.on_elements is not None:
            await client.set_switch(indi_name, prop_name, body.on_elements)
        elif body.values is not None:
            # Detect type from first value
            first = next(iter(body.values.values()), None)
            if isinstance(first, (int, float)):
                await client.set_number(indi_name, prop_name,
                                        {k: float(v) for k, v in body.values.items()})
            else:
                await client.set_text(indi_name, prop_name,
                                      {k: str(v) for k, v in body.values.items()})
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    _follow_pin(request, device_id, prop_name, body)


def _follow_pin(request: Request, device_id: str, prop_name: str, body: SetPropertyRequest) -> None:
    """A pinned property that is set again keeps the new value."""
    item, pins = _item_and_pins(request, device_id)
    if item is None or prop_name not in pins:
        return
    if body.on_elements is not None:
        spec = pinlib.pin_spec("switch", {name: True for name in body.on_elements})
    elif body.values is not None:
        first = next(iter(body.values.values()), None)
        spec = pinlib.pin_spec("number" if isinstance(first, (int, float)) else "text", body.values)
    else:
        return
    if spec is not None:
        _store_pins(request, device_id, item, {**pins, prop_name: spec})
