"""
GET  /devices/{device_id}/properties        — snapshot of all live INDI properties
POST /devices/{device_id}/properties/{prop} — set a number, switch, or text property
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

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

_IPS = {0: "idle", 1: "ok", 2: "busy", 3: "alert"}
_IPERM = {0: "ro", 1: "wo", 2: "rw"}
_ISR = {0: "1ofmany", 1: "atmost1", 2: "nofmany"}


def _prop_to_out(p: Any) -> PropertyOut | None:
    """Convert a PyIndi Property to PropertyOut. Returns None for BLOBs."""
    try:
        import PyIndi  # type: ignore[import]
    except ImportError:
        return None

    ptype = p.getType()
    name = p.getName()
    label = p.getLabel() or name
    group = p.getGroupName() or ""
    state = _IPS.get(int(p.getState()), "idle")
    perm = _IPERM.get(int(p.getPermission()), "ro")

    if ptype == PyIndi.INDI_NUMBER:
        pn = p.getNumber()
        widgets = [
            PropertyWidget(
                name=pn[i].getName(),
                label=pn[i].getLabel() or pn[i].getName(),
                value=float(pn[i].getValue()),
                min=float(pn[i].getMin()),
                max=float(pn[i].getMax()),
                step=float(pn[i].getStep()),
            )
            for i in range(pn.count())
        ]
        return PropertyOut(name=name, label=label, group=group, type="number",
                           state=state, permission=perm, widgets=widgets)

    if ptype == PyIndi.INDI_SWITCH:
        ps = p.getSwitch()
        rule = _ISR.get(int(ps.getRule()), "1ofmany")
        widgets = [
            PropertyWidget(
                name=ps[i].getName(),
                label=ps[i].getLabel() or ps[i].getName(),
                value=(ps[i].s == PyIndi.ISS_ON),
            )
            for i in range(ps.count())
        ]
        return PropertyOut(name=name, label=label, group=group, type="switch",
                           state=state, permission=perm, switch_rule=rule,
                           widgets=widgets)

    if ptype == PyIndi.INDI_TEXT:
        pt = p.getText()
        widgets = [
            PropertyWidget(
                name=pt[i].getName(),
                label=pt[i].getLabel() or pt[i].getName(),
                value=pt[i].getText() or "",
            )
            for i in range(pt.count())
        ]
        return PropertyOut(name=name, label=label, group=group, type="text",
                           state=state, permission=perm, widgets=widgets)

    if ptype == PyIndi.INDI_LIGHT:
        pl = p.getLight()
        widgets = [
            PropertyWidget(
                name=pl[i].getName(),
                label=pl[i].getLabel() or pl[i].getName(),
                state=_IPS.get(int(pl[i].s), "idle"),
            )
            for i in range(pl.count())
        ]
        return PropertyOut(name=name, label=label, group=group, type="light",
                           state=state, permission="ro", widgets=widgets)

    return None  # BLOB or unknown


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

@router.get("/{device_id}/properties", response_model=list[PropertyOut])
async def get_properties(device_id: str, request: Request) -> list[PropertyOut]:
    """Return a live snapshot of all INDI properties for a connected device."""
    client = _get_indi_client(request)
    indi_name = _resolve_indi_name(device_id, request)
    snapshot = await client.get_properties_snapshot(indi_name)
    props = [_prop_to_out(p) for p in snapshot.values()]
    result = [p for p in props if p is not None]
    result.sort(key=lambda x: (x.group, x.name))
    return result


@router.post("/{device_id}/properties/{prop_name}", status_code=204)
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
