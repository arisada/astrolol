"""The tools the MCP endpoint offers: a curated subset of astrolol's REST API.

Each tool is a thin wrapper over one or a few REST calls made as the caller (see
``loopback``). Long operations (slew, park, autofocus, centering) can wait for completion so
the model does not have to poll; every wait has a timeout and returns the state it found.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI

from astrolol.plugins.mcp.loopback import ApiClient, ToolError, safe_id


class Blocks(list[dict[str, Any]]):
    """Ready-made MCP content blocks (text, images); any other result is sent as JSON text."""


Handler = Callable[["ToolContext", dict[str, Any]], Awaitable[Any]]


@dataclass
class ToolContext:
    app: FastAPI
    api: ApiClient
    event_bus: Any = None

    def plugin_enabled(self, plugin_id: str) -> bool:
        return plugin_id in getattr(self.app.state, "enabled_plugin_ids", set())

    @contextmanager
    def watch(self) -> Iterator[Waiter]:
        """Listen to the event bus from now on (start before the call that causes the event)."""
        waiter = Waiter(self.event_bus)
        try:
            yield waiter
        finally:
            waiter.close()


class Waiter:
    def __init__(self, bus: Any) -> None:
        self._bus = bus
        self._q = bus.subscribe() if bus is not None else None

    def close(self) -> None:
        if self._bus is not None and self._q is not None:
            self._bus.unsubscribe(self._q)

    async def until(self, accept: Callable[[Any], bool], timeout: float) -> Any | None:
        """The first event for which *accept* is true, or None after *timeout* seconds."""
        if self._q is None:
            return None
        try:
            async with asyncio.timeout(timeout):
                while True:
                    event = await self._q.get()
                    if accept(event):
                        return event
        except TimeoutError:
            return None


@dataclass
class Tool:
    name: str
    description: str
    properties: dict[str, Any]
    required: list[str]
    handler: Handler
    read_only: bool = False
    destructive: bool = False
    idempotent: bool = False
    plugins: tuple[str, ...] = ()  # offered only when at least one of these plugins is enabled

    def available(self, ctx: ToolContext) -> bool:
        return not self.plugins or any(ctx.plugin_enabled(p) for p in self.plugins)

    def describe(self) -> dict[str, Any]:
        schema: dict[str, Any] = {"type": "object", "properties": self.properties}
        if self.required:
            schema["required"] = self.required
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": schema,
            "annotations": {
                "readOnlyHint": self.read_only,
                "destructiveHint": self.destructive and not self.read_only,
                "idempotentHint": self.idempotent or self.read_only,
                "openWorldHint": False,
            },
        }

    async def run(self, ctx: ToolContext, args: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.available(ctx):
            raise ToolError(f"{self.name} needs the {' or '.join(self.plugins)} plugin, which is not enabled")
        missing = [r for r in self.required if args.get(r) is None]
        if missing:
            raise ToolError(f"Missing argument(s): {', '.join(missing)}")
        unknown = sorted(set(args) - set(self.properties))
        if unknown:
            raise ToolError(f"Unknown argument(s): {', '.join(unknown)}")
        result = await self.handler(ctx, args)
        if isinstance(result, Blocks):
            return list(result)
        return [text(result)]


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def add(self, tool: Tool) -> None:
        assert tool.name not in self._tools, tool.name
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def describe(self, ctx: ToolContext) -> list[dict[str, Any]]:
        return [t.describe() for t in self._tools.values() if t.available(ctx)]

    def names(self) -> list[str]:
        return list(self._tools)


REGISTRY = Registry()  # the fixed table of tool definitions; holds no per-app state


def text(obj: Any) -> dict[str, Any]:
    body = obj if isinstance(obj, str) else json.dumps(obj, default=str, separators=(",", ":"))
    return {"type": "text", "text": body}


def tool(
    name: str,
    description: str,
    props: dict[str, Any] | None = None,
    required: tuple[str, ...] = (),
    *,
    read_only: bool = False,
    destructive: bool = False,
    idempotent: bool = False,
    plugins: tuple[str, ...] = (),
) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        REGISTRY.add(Tool(name, description, props or {}, list(required), fn,
                          read_only, destructive, idempotent, plugins))
        return fn
    return deco


# ── schema shorthands ─────────────────────────────────────────────────────────

def S(desc: str, **kw: Any) -> dict[str, Any]:
    return {"type": "string", "description": desc, **kw}


def N(desc: str, **kw: Any) -> dict[str, Any]:
    return {"type": "number", "description": desc, **kw}


def I(desc: str, **kw: Any) -> dict[str, Any]:  # noqa: E743
    return {"type": "integer", "description": desc, **kw}


def B(desc: str, default: bool | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "boolean", "description": desc}
    if default is not None:
        out["default"] = default
    return out


def O(desc: str) -> dict[str, Any]:  # noqa: E743
    return {"type": "object", "description": desc}


DEVICE = S("Device id from list_devices / get_overview, e.g. mount_eqmod_telescope")
WAIT = B("Return only when the operation has finished (or timeout_s passed)", True)
TIMEOUT = N("Longest wait in seconds", default=300)


def _timeout(args: dict[str, Any], default: float) -> float:
    return max(1.0, min(float(args.get("timeout_s") or default), 3600.0))


def _drop(args: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in args.items() if k not in keys and v is not None}


async def _poll(
    fetch: Callable[[], Awaitable[Any]], done: Callable[[Any], bool], timeout: float, interval: float = 1.5
) -> tuple[Any, bool]:
    """Fetch until *done*; returns (last value, finished)."""
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while True:
        value = await fetch()
        if done(value):
            return value, True
        if loop.time() + interval > end:
            return value, False
        await asyncio.sleep(interval)


def _thin(obj: Any, keep: int = 24) -> Any:
    """Cut long lists (altitude curves, histories) to evenly spaced samples."""
    if isinstance(obj, list):
        if len(obj) > keep:
            step = len(obj) / keep
            obj = [obj[int(i * step)] for i in range(keep)]
        return [_thin(x, keep) for x in obj]
    if isinstance(obj, dict):
        return {k: _thin(v, keep) for k, v in obj.items()}
    return obj


# ── overview & events ─────────────────────────────────────────────────────────

_STATUS_PATH = {
    "mount": "/mount/{}/status",
    "camera": "/imager/{}/status",
    "focuser": "/focuser/{}/status",
    "filter_wheel": "/filter_wheel/{}/status",
}


async def _safe(coro: Awaitable[Any]) -> Any:
    try:
        return await coro
    except ToolError as exc:
        return {"error": str(exc)}


def _guider_plugin(ctx: ToolContext) -> str:
    for pid in ("guider", "phd2", "guide_simulator"):
        if ctx.plugin_enabled(pid):
            return pid
    raise ToolError("No guider plugin is enabled (guider, phd2 or guide_simulator)")


async def _autofocus_state(api: ApiClient) -> Any:
    resp = await _safe(api.call("GET", "/plugins/autofocus/run", ok_missing=True))
    if isinstance(resp, dict) or resp.status != 200:
        return resp if isinstance(resp, dict) else None
    return {k: resp.data.get(k) for k in ("status", "current_step", "total_steps", "optimal_position", "error")}


@tool("get_overview",
      "Everything at a glance: active profile, connected devices with their live status "
      "(mount position and tracking, camera, focuser, filter wheel), guiding, autofocus and sequencer. "
      "Call this first. RA in status values is in hours, Dec in degrees.",
      read_only=True)
async def get_overview(ctx: ToolContext, args: dict[str, Any]) -> Any:
    api = ctx.api
    profile, devices = await asyncio.gather(
        _safe(api.get("/profiles/active")), _safe(api.get("/devices/connected")))
    out: dict[str, Any] = {"time_utc": datetime.now(UTC).isoformat(timespec="seconds")}
    out["active_profile"] = (
        {"id": profile.get("id"), "name": profile.get("name")} if isinstance(profile, dict) and "error" not in profile
        else profile)
    out["devices"] = devices
    jobs: dict[str, Awaitable[Any]] = {}
    if isinstance(devices, list):
        for d in devices:
            path = _STATUS_PATH.get(d.get("kind", ""))
            if path and d.get("state") == "connected":
                jobs[d["device_id"]] = _safe(api.get(path.format(safe_id(d["device_id"]))))
    if ctx.plugin_enabled("sequencer"):
        jobs["_sequencer"] = _safe(api.get("/plugins/sequencer/status"))
    if any(ctx.plugin_enabled(p) for p in ("guider", "phd2", "guide_simulator")):
        jobs["_guiding"] = _safe(api.get(f"/plugins/{_guider_plugin(ctx)}/status"))
    if ctx.plugin_enabled("autofocus"):
        jobs["_autofocus"] = _autofocus_state(api)
    results = dict(zip(jobs, await asyncio.gather(*jobs.values()), strict=True))
    out["status"] = {k: v for k, v in results.items() if not k.startswith("_")}
    for key in ("sequencer", "guiding", "autofocus"):
        if f"_{key}" in results:
            out[key] = results[f"_{key}"]
    return out


@tool("list_devices", "Connected devices: id, kind (camera, mount, focuser, filter_wheel, …), adapter, state.",
      read_only=True)
async def list_devices(ctx: ToolContext, args: dict[str, Any]) -> Any:
    return await ctx.api.get("/devices/connected")


@tool("get_events",
      "Recent events from the server's log of what happened (exposures, slews, errors, guiding, sequencer). "
      "Use it to find out why something stopped. Newest last.",
      {"type_prefix": S("Keep only event types starting with this, e.g. 'mount', 'sequencer', 'imager.exposure'"),
       "limit": I("How many to return", default=30, minimum=1, maximum=200)},
      read_only=True)
async def get_events(ctx: ToolContext, args: dict[str, Any]) -> Any:
    events = await ctx.api.get("/events/history")
    prefix = args.get("type_prefix")
    if prefix:
        events = [e for e in events if str(e.get("type", "")).startswith(prefix)]
    events = [e for e in events if e.get("type") not in {"focuser.position_updated", "mount.coords_updated"}]
    out = []
    for e in events[-int(args.get("limit") or 30):]:
        slim = {k: v for k, v in e.items() if k not in {"id", "notify", "notify_title"} and v is not None}
        out.append(slim)
    return out


@tool("api_get",
      "Read-only escape hatch: GET any astrolol REST path and return the JSON, for things the other tools "
      "do not cover (the full API is documented at /docs). Cannot change anything.",
      {"path": S("Path starting with /, e.g. /plugins/target/settings"),
       "query": O("Query parameters")},
      ("path",), read_only=True)
async def api_get(ctx: ToolContext, args: dict[str, Any]) -> Any:
    path = args["path"]
    if (not isinstance(path, str) or not path.startswith("/") or "//" in path or ".." in path
            or "?" in path or "#" in path or "\\" in path):
        raise ToolError("path must be an absolute path such as /mount/<id>/status, without a query string")
    if path.split("/")[1] in {"auth", "admin"}:
        raise ToolError("That area is not available through MCP")
    resp = await ctx.api.call("GET", path, params=args.get("query") or {})
    if resp.data is None:
        return f"{resp.status}, {len(resp.body)} bytes of {resp.content_type or 'unknown type'}"
    return _thin(resp.data, 60)


# ── profiles ──────────────────────────────────────────────────────────────────

@tool("list_profiles", "Equipment profiles (a named set of devices to connect).", read_only=True)
async def list_profiles(ctx: ToolContext, args: dict[str, Any]) -> Any:
    profiles = await ctx.api.get("/profiles")
    return [{"id": p.get("id"), "name": p.get("name")} for p in profiles]


@tool("activate_profile",
      "Make a profile the active one and connect all its devices (best effort: failures are listed in the result).",
      {"profile_id": S("Profile id from list_profiles")}, ("profile_id",), idempotent=True)
async def activate_profile(ctx: ToolContext, args: dict[str, Any]) -> Any:
    return await ctx.api.post(f"/profiles/{safe_id(args['profile_id'], 'profile_id')}/activate", timeout=180)


# ── targets ───────────────────────────────────────────────────────────────────

@tool("search_objects",
      "Find a sky object by name (M31, NGC 7000, Vega, Jupiter, …). Returns ICRS coordinates in DEGREES "
      "(ra 0–360, dec −90..90), the form mount_slew, mount_set_target and platesolve_center take.",
      {"query": S("Name or catalogue designation"), "limit": I("Maximum matches", default=5, minimum=1, maximum=50)},
      ("query",), read_only=True)
async def search_objects(ctx: ToolContext, args: dict[str, Any]) -> Any:
    return await ctx.api.get("/plugins/object_resolver/search",
                             params={"q": args["query"], "limit": args.get("limit") or 5})


@tool("target_visibility",
      "When an object rises, transits and sets tonight at the observing site, twilight times and the Moon, "
      "plus a sampled altitude curve. Needs a site in the active profile.",
      {"ra_deg": N("ICRS right ascension, degrees"), "dec_deg": N("ICRS declination, degrees"),
       "date": S("ISO date; default today (UTC)")},
      ("ra_deg", "dec_deg"), read_only=True, plugins=("target",))
async def target_visibility(ctx: ToolContext, args: dict[str, Any]) -> Any:
    data = await ctx.api.get("/plugins/target/ephemeris",
                             params={"ra": args["ra_deg"], "dec": args["dec_deg"], "date": args.get("date")})
    return _thin(data)


# ── mount ─────────────────────────────────────────────────────────────────────

@tool("mount_status",
      "Mount state: RA (hours) / Dec (degrees), altitude/azimuth, tracking, parked, slewing, pier side, "
      "hour angle and local sidereal time.",
      {"device_id": DEVICE}, ("device_id",), read_only=True)
async def mount_status(ctx: ToolContext, args: dict[str, Any]) -> Any:
    return await ctx.api.get(f"/mount/{safe_id(args['device_id'])}/status")


async def _mount_target(ctx: ToolContext, args: dict[str, Any]) -> None:
    ra, dec = args.get("ra_deg"), args.get("dec_deg")
    if (ra is None) != (dec is None):
        raise ToolError("Give both ra_deg and dec_deg, or neither to use the current target")
    if ra is not None:
        body = {"ra": ra, "dec": dec, "name": args.get("name"), "frame": args.get("frame") or "icrs"}
        await ctx.api.put(f"/mount/{safe_id(args['device_id'])}/target", _drop(body))


@tool("mount_set_target",
      "Set the mount's target without moving. Coordinates in DEGREES (see search_objects).",
      {"device_id": DEVICE, "ra_deg": N("Right ascension, degrees (0–360)"), "dec_deg": N("Declination, degrees"),
       "name": S("Target name, kept in FITS headers"), "frame": S("icrs (J2000, default) or jnow", enum=["icrs", "jnow"])},
      ("device_id", "ra_deg", "dec_deg"), idempotent=True)
async def mount_set_target(ctx: ToolContext, args: dict[str, Any]) -> Any:
    await _mount_target(ctx, args)
    return await ctx.api.get(f"/mount/{safe_id(args['device_id'])}/target")


@tool("mount_slew",
      "Slew to a target and (by default) wait until the mount arrives. Moves hardware: confirm the target is "
      "above the horizon and the mount is unparked and clear to move. Pass ra_deg/dec_deg (degrees), or omit them to "
      "go to the target set earlier. Stop guiding first if it is running.",
      {"device_id": DEVICE, "ra_deg": N("Right ascension, degrees (0–360)"), "dec_deg": N("Declination, degrees"),
       "name": S("Target name"), "frame": S("icrs (default) or jnow", enum=["icrs", "jnow"]),
       "wait": WAIT, "timeout_s": TIMEOUT},
      ("device_id",), destructive=True)
async def mount_slew(ctx: ToolContext, args: dict[str, Any]) -> Any:
    dev = safe_id(args["device_id"])
    await _mount_target(ctx, args)
    with ctx.watch() as w:
        await ctx.api.post(f"/mount/{dev}/slew")
        if args.get("wait", True):
            ev = await w.until(
                lambda e: getattr(e, "device_id", None) == dev and e.type in
                {"mount.slew_completed", "mount.slew_aborted", "mount.operation_failed"}, _timeout(args, 300))
            if ev is None:
                return {"result": "timeout", "note": "Still slewing; check mount_status", **await _mstatus(ctx, dev)}
            if ev.type == "mount.slew_aborted":
                raise ToolError("The slew was aborted")
            if ev.type == "mount.operation_failed":
                raise ToolError(f"The slew failed: {ev.reason}")
            return {"result": "arrived", **await _mstatus(ctx, dev)}
    return {"result": "slewing"}


async def _mstatus(ctx: ToolContext, dev: str) -> dict[str, Any]:
    st = await ctx.api.get(f"/mount/{dev}/status")
    return {"status": {k: st.get(k) for k in
                       ("ra", "dec", "alt", "az", "is_tracking", "is_slewing", "is_parked", "pier_side")}}


@tool("mount_stop", "Abort any slew or park and halt the motors.", {"device_id": DEVICE}, ("device_id",),
      idempotent=True)
async def mount_stop(ctx: ToolContext, args: dict[str, Any]) -> Any:
    await ctx.api.post(f"/mount/{safe_id(args['device_id'])}/stop")
    return "stopped"


@tool("mount_park", "Park the mount at its park position and (by default) wait. Do this at the end of a session.",
      {"device_id": DEVICE, "wait": WAIT, "timeout_s": TIMEOUT}, ("device_id",), idempotent=True)
async def mount_park(ctx: ToolContext, args: dict[str, Any]) -> Any:
    dev = safe_id(args["device_id"])
    with ctx.watch() as w:
        await ctx.api.post(f"/mount/{dev}/park")
        if not args.get("wait", True):
            return {"result": "parking"}
        ev = await w.until(lambda e: getattr(e, "device_id", None) == dev and e.type in
                           {"mount.parked", "mount.operation_failed", "mount.slew_aborted"}, _timeout(args, 300))
    if ev is None:
        return {"result": "timeout", "note": "Still parking; check mount_status"}
    if ev.type != "mount.parked":
        raise ToolError(f"Parking did not finish: {getattr(ev, 'reason', ev.type)}")
    return {"result": "parked"}


@tool("mount_unpark", "Unpark the mount so it can move.", {"device_id": DEVICE}, ("device_id",), idempotent=True)
async def mount_unpark(ctx: ToolContext, args: dict[str, Any]) -> Any:
    await ctx.api.post(f"/mount/{safe_id(args['device_id'])}/unpark")
    return "unparked"


@tool("mount_set_tracking", "Turn sidereal (or other) tracking on or off.",
      {"device_id": DEVICE, "enabled": B("Tracking on/off"),
       "mode": S("Tracking mode if the mount has several, e.g. sidereal, lunar, solar")},
      ("device_id", "enabled"), idempotent=True)
async def mount_set_tracking(ctx: ToolContext, args: dict[str, Any]) -> Any:
    await ctx.api.post(f"/mount/{safe_id(args['device_id'])}/tracking", _drop(args, "device_id"))
    return "ok"


@tool("mount_sync",
      "Tell the mount it is pointing at these ICRS coordinates (degrees), which changes its pointing model. "
      "Use it only with a verified position, for example from a plate solve.",
      {"device_id": DEVICE, "ra_deg": N("Right ascension, degrees"), "dec_deg": N("Declination, degrees")},
      ("device_id", "ra_deg", "dec_deg"), destructive=True)
async def mount_sync(ctx: ToolContext, args: dict[str, Any]) -> Any:
    await ctx.api.post(f"/mount/{safe_id(args['device_id'])}/sync", {"ra": args["ra_deg"], "dec": args["dec_deg"]})
    return "synced"


@tool("mount_meridian_flip", "Flip the mount across the meridian and (by default) wait. Stop guiding first.",
      {"device_id": DEVICE, "wait": WAIT, "timeout_s": TIMEOUT}, ("device_id",), destructive=True)
async def mount_meridian_flip(ctx: ToolContext, args: dict[str, Any]) -> Any:
    dev = safe_id(args["device_id"])
    with ctx.watch() as w:
        await ctx.api.post(f"/mount/{dev}/meridian_flip")
        if not args.get("wait", True):
            return {"result": "flipping"}
        ev = await w.until(lambda e: getattr(e, "device_id", None) == dev and e.type in
                           {"mount.meridian_flip_completed", "mount.operation_failed", "mount.slew_aborted"},
                           _timeout(args, 600))
    if ev is None:
        return {"result": "timeout", "note": "Still flipping; check mount_status"}
    if ev.type != "mount.meridian_flip_completed":
        raise ToolError(f"The flip did not finish: {getattr(ev, 'reason', ev.type)}")
    return {"result": "flipped", **await _mstatus(ctx, dev)}


# ── camera ────────────────────────────────────────────────────────────────────

async def _preview_block(ctx: ToolContext, dev: str, max_px: int) -> dict[str, Any] | None:
    resp = await ctx.api.call("GET", f"/imager/{dev}/preview.jpg", params={"quality": 70}, ok_missing=True)
    if resp.status != 200 or not resp.body:
        return None

    def shrink() -> bytes:
        from PIL import Image
        im = Image.open(io.BytesIO(resp.body))
        im.thumbnail((max_px, max_px))
        out = io.BytesIO()
        im.convert("RGB").save(out, "JPEG", quality=75)
        return out.getvalue()

    data = await asyncio.to_thread(shrink)
    return {"type": "image", "data": base64.b64encode(data).decode(), "mimeType": "image/jpeg"}


@tool("camera_expose",
      "Take one exposure, wait for it, and return its file path, size, statistics and a stretched preview image. "
      "The preview is a quick look, not the saved data.",
      {"device_id": DEVICE, "duration_s": N("Exposure time in seconds", exclusiveMinimum=0),
       "gain": I("Gain; omit to keep the camera's current gain"), "binning": I("Binning", default=1, minimum=1, maximum=4),
       "frame_type": S("light, dark, flat or bias", enum=["light", "dark", "flat", "bias"], default="light"),
       "save": B("Save the FITS file (false = look only)", True),
       "object_name": S("Object name for the FITS header; default the mount target"),
       "include_preview": B("Attach a preview image", True),
       "preview_max_px": I("Longest side of the preview", default=900, minimum=200, maximum=2000)},
      ("device_id", "duration_s"))
async def camera_expose(ctx: ToolContext, args: dict[str, Any]) -> Any:
    dev = safe_id(args["device_id"])
    body = _drop({"duration": args["duration_s"], "gain": args.get("gain"), "binning": args.get("binning"),
                  "frame_type": args.get("frame_type"), "save": args.get("save"),
                  "object_name": args.get("object_name")})
    result = await ctx.api.post(f"/imager/{dev}/expose", body, timeout=float(args["duration_s"]) + 180)
    stats = await ctx.api.call("GET", f"/imager/{dev}/stats", ok_missing=True)
    out: dict[str, Any] = {"result": {k: result.get(k) for k in ("fits_path", "duration", "width", "height")}}
    if stats.status == 200:
        out["stats"] = stats.data
    content = Blocks([text(out)])
    if args.get("include_preview", True):
        block = await _preview_block(ctx, dev, int(args.get("preview_max_px") or 900))
        if block:
            content.append(block)
    return content


@tool("camera_preview",
      "The last exposure of a camera again, as a stretched image (no new exposure).",
      {"device_id": DEVICE, "max_px": I("Longest side", default=900, minimum=200, maximum=2000)},
      ("device_id",), read_only=True)
async def camera_preview(ctx: ToolContext, args: dict[str, Any]) -> Any:
    block = await _preview_block(ctx, safe_id(args["device_id"]), int(args.get("max_px") or 900))
    if block is None:
        raise ToolError("This camera has not taken an exposure yet")
    return Blocks([block])


@tool("camera_status", "Camera state: exposing/looping/idle, sensor temperature, cooler and its power.",
      {"device_id": DEVICE}, ("device_id",), read_only=True)
async def camera_status(ctx: ToolContext, args: dict[str, Any]) -> Any:
    dev = safe_id(args["device_id"])
    imager, hw = await asyncio.gather(ctx.api.get(f"/imager/{dev}/status"),
                                      _safe(ctx.api.get(f"/imager/{dev}/camera_status")))
    return {"imager": imager, "camera": hw}


@tool("camera_set_cooler", "Turn the camera cooler on/off and optionally set the target sensor temperature (°C).",
      {"device_id": DEVICE, "enabled": B("Cooler on/off"), "target_temperature": N("Target in °C")},
      ("device_id", "enabled"), idempotent=True)
async def camera_set_cooler(ctx: ToolContext, args: dict[str, Any]) -> Any:
    await ctx.api.post(f"/imager/{safe_id(args['device_id'])}/cooler", _drop(args, "device_id"))
    return "ok"


@tool("camera_halt", "Abort the running exposure and any loop on this camera.",
      {"device_id": DEVICE}, ("device_id",), idempotent=True)
async def camera_halt(ctx: ToolContext, args: dict[str, Any]) -> Any:
    await ctx.api.post(f"/imager/{safe_id(args['device_id'])}/halt")
    return "halted"


# ── focuser, filter wheel, autofocus ──────────────────────────────────────────

@tool("focuser_status", "Focuser position, whether it is moving, and temperature if it has a sensor.",
      {"device_id": DEVICE}, ("device_id",), read_only=True)
async def focuser_status(ctx: ToolContext, args: dict[str, Any]) -> Any:
    return await ctx.api.get(f"/focuser/{safe_id(args['device_id'])}/status")


@tool("focuser_move",
      "Move the focuser to an absolute position, or by a number of steps (positive = out), and wait.",
      {"device_id": DEVICE, "position": I("Absolute target position"),
       "steps": I("Relative move; positive = out, negative = in"), "wait": WAIT, "timeout_s": N("Longest wait", default=120)},
      ("device_id",))
async def focuser_move(ctx: ToolContext, args: dict[str, Any]) -> Any:
    dev = safe_id(args["device_id"])
    if (args.get("position") is None) == (args.get("steps") is None):
        raise ToolError("Give exactly one of position and steps")
    with ctx.watch() as w:
        if args.get("position") is not None:
            await ctx.api.post(f"/focuser/{dev}/move_to", {"position": args["position"]})
        else:
            await ctx.api.post(f"/focuser/{dev}/move_by", {"steps": args["steps"]})
        if not args.get("wait", True):
            return {"result": "moving"}
        ev = await w.until(lambda e: getattr(e, "device_id", None) == dev and e.type in
                           {"focuser.move_completed", "focuser.halted"}, _timeout(args, 120))
    st = await ctx.api.get(f"/focuser/{dev}/status")
    if ev is None:
        return {"result": "timeout", "status": st}
    return {"result": "halted" if ev.type == "focuser.halted" else "arrived", "status": st}


@tool("focuser_halt", "Stop a focuser move immediately.", {"device_id": DEVICE}, ("device_id",), idempotent=True)
async def focuser_halt(ctx: ToolContext, args: dict[str, Any]) -> Any:
    await ctx.api.post(f"/focuser/{safe_id(args['device_id'])}/halt")
    return "halted"


@tool("filter_wheel_status", "Filter wheel: current slot and the filter names.",
      {"device_id": DEVICE}, ("device_id",), read_only=True)
async def filter_wheel_status(ctx: ToolContext, args: dict[str, Any]) -> Any:
    return await ctx.api.get(f"/filter_wheel/{safe_id(args['device_id'])}/status")


@tool("filter_wheel_select", "Rotate the filter wheel to a slot (see filter_wheel_status for slot numbers).",
      {"device_id": DEVICE, "slot": I("Slot number")}, ("device_id", "slot"), idempotent=True)
async def filter_wheel_select(ctx: ToolContext, args: dict[str, Any]) -> Any:
    await ctx.api.post(f"/filter_wheel/{safe_id(args['device_id'])}/select", {"slot": args["slot"]})
    return await ctx.api.get(f"/filter_wheel/{safe_id(args['device_id'])}/status")


@tool("autofocus_start",
      "Run an autofocus sweep: takes a series of exposures at focuser positions around the start position, fits "
      "the best focus and moves there. Needs a star field; wait for it by default. Returns the run with its result.",
      {"camera_id": S("Camera device id"), "focuser_id": S("Focuser device id"),
       "exposure_s": N("Exposure per step, seconds", default=2),
       "step_size": I("Focuser steps between samples", default=100), "num_steps": I("Steps each side (3–15)", default=5),
       "binning": I("Binning", default=1), "gain": I("Gain"), "filter_slot": I("Filter slot to select first"),
       "filter_wheel_id": S("Filter wheel device id when there are several"),
       "metric": S("hfd or fwhm", enum=["hfd", "fwhm"]),
       "wait": WAIT, "timeout_s": N("Longest wait", default=900)},
      ("camera_id", "focuser_id"), plugins=("autofocus",))
async def autofocus_start(ctx: ToolContext, args: dict[str, Any]) -> Any:
    cfg = _drop(args, "wait", "timeout_s", "exposure_s")
    if args.get("exposure_s") is not None:
        cfg["exposure_time"] = args["exposure_s"]
    run = await ctx.api.post("/plugins/autofocus/start", cfg)
    if not args.get("wait", True):
        return _af_summary(run)
    run, done = await _poll(lambda: ctx.api.get("/plugins/autofocus/run"),
                            lambda r: r.get("status") != "running", _timeout(args, 900), 2.0)
    out = _af_summary(run)
    if not done:
        out["note"] = "Still running; poll autofocus_status"
    return out


def _af_summary(run: dict[str, Any]) -> dict[str, Any]:
    keys = ("status", "current_step", "total_steps", "optimal_position", "initial_position", "error")
    out = {k: run.get(k) for k in keys}
    out["samples"] = [{"position": p.get("position"), "fwhm": p.get("fwhm"), "stars": p.get("star_count")}
                      for p in run.get("data_points", [])]
    if run.get("curve_fit"):
        out["curve_fit"] = run["curve_fit"]
    return out


@tool("autofocus_status", "State and result of the current or last autofocus run.", read_only=True,
      plugins=("autofocus",))
async def autofocus_status(ctx: ToolContext, args: dict[str, Any]) -> Any:
    resp = await ctx.api.call("GET", "/plugins/autofocus/run", ok_missing=True)
    return _af_summary(resp.data) if resp.status == 200 else "No autofocus run yet"


@tool("autofocus_abort", "Abort a running autofocus.", idempotent=True, plugins=("autofocus",))
async def autofocus_abort(ctx: ToolContext, args: dict[str, Any]) -> Any:
    await ctx.api.post("/plugins/autofocus/abort")
    return "aborted"


# ── plate solving ─────────────────────────────────────────────────────────────

@tool("platesolve_center",
      "Centre on a target precisely: slew, take a short exposure, plate-solve, sync and re-slew until the error "
      "is within tolerance. Needs the astap solver. Coordinates in DEGREES.",
      {"mount_id": S("Mount device id"), "camera_id": S("Camera device id"),
       "ra_deg": N("Target right ascension, degrees"), "dec_deg": N("Target declination, degrees"),
       "name": S("Target name"), "tolerance_arcsec": N("Accept when this close", default=60),
       "max_attempts": I("Solve attempts", default=5), "exposure_s": N("Solve exposure, seconds", default=5),
       "binning": I("Binning", default=2), "gain": I("Gain"),
       "slew_first": B("Slew before the first solve", True), "wait": WAIT, "timeout_s": N("Longest wait", default=600)},
      ("mount_id", "camera_id", "ra_deg", "dec_deg"), destructive=True, plugins=("platesolve",))
async def platesolve_center(ctx: ToolContext, args: dict[str, Any]) -> Any:
    body = _drop(args, "wait", "timeout_s", "ra_deg", "dec_deg", "exposure_s")
    body.update(ra=args["ra_deg"], dec=args["dec_deg"])
    if args.get("exposure_s") is not None:
        body["exposure_s"] = args["exposure_s"]
    safe_id(args["mount_id"]), safe_id(args["camera_id"])
    run = await ctx.api.post("/plugins/platesolve/center", body)
    if not args.get("wait", True):
        return {"status": run.get("status")}
    run, done = await _poll(lambda: ctx.api.get("/plugins/platesolve/center"),
                            lambda r: r.get("status") != "running", _timeout(args, 600), 2.0)
    out = {"status": run.get("status"), "result": run.get("result"), "error": run.get("error")}
    if not done:
        out["note"] = "Still running; poll platesolve_center_status"
    return out


@tool("platesolve_center_status", "State and result of the current or last centering run.", read_only=True,
      plugins=("platesolve",))
async def platesolve_center_status(ctx: ToolContext, args: dict[str, Any]) -> Any:
    resp = await ctx.api.call("GET", "/plugins/platesolve/center", ok_missing=True)
    if resp.status != 200:
        return "No centering run yet"
    run = resp.data
    return {"status": run.get("status"), "result": run.get("result"), "error": run.get("error")}


@tool("platesolve_cancel_center", "Cancel a running centering.", idempotent=True, plugins=("platesolve",))
async def platesolve_cancel_center(ctx: ToolContext, args: dict[str, Any]) -> Any:
    await ctx.api.delete("/plugins/platesolve/center")
    return "cancelled"


@tool("platesolve_here",
      "Take an exposure and plate-solve it: where is the telescope really pointing? Returns RA/Dec in degrees, "
      "field rotation and pixel scale. Does not move or sync anything.",
      {"camera_id": S("Camera device id"), "exposure_s": N("Exposure, seconds", default=5),
       "binning": I("Binning", default=2), "gain": I("Gain"), "timeout_s": N("Longest wait", default=180)},
      ("camera_id",), plugins=("platesolve",))
async def platesolve_here(ctx: ToolContext, args: dict[str, Any]) -> Any:
    body = _drop({"device_id": safe_id(args["camera_id"]), "duration": args.get("exposure_s") or 5,
                  "binning": args.get("binning") or 2, "gain": args.get("gain")})
    job = await ctx.api.post("/plugins/platesolve/expose_and_solve", body)
    job_id = safe_id(job["id"])
    job, done = await _poll(lambda: ctx.api.get(f"/plugins/platesolve/{job_id}/status"),
                            lambda j: j.get("status") in {"completed", "failed", "cancelled"},
                            _timeout(args, 180), 1.5)
    if not done:
        await _safe(ctx.api.delete(f"/plugins/platesolve/{job_id}/cancel"))
        raise ToolError("The solve did not finish in time")
    if job.get("status") != "completed":
        raise ToolError(f"Solve {job.get('status')}: {job.get('error') or 'no solution'}")
    return job.get("result")


# ── guiding ───────────────────────────────────────────────────────────────────

_SETTLE = O("Settle criteria: {pixels, time, timeout} (defaults 1.5 px, 10 s, 60 s)")


@tool("guiding_status", "Guider state: guiding or not, star lost, RMS error (arcsec), settling, calibration.",
      read_only=True, plugins=("guider", "phd2", "guide_simulator"))
async def guiding_status(ctx: ToolContext, args: dict[str, Any]) -> Any:
    pid = _guider_plugin(ctx)
    status = await ctx.api.get(f"/plugins/{pid}/status")
    if pid == "phd2":
        health = await _safe(ctx.api.get("/plugins/phd2/health"))
        return {"guider": pid, "status": status, "health": health}
    if isinstance(status, dict):  # drop bulky calibration detail
        status = {k: v for k, v in status.items() if k not in {"calibration", "active_calibration", "darks"}}
    return {"guider": pid, "status": status}


@tool("guiding_start",
      "Start guiding (calibrates first if needed). Returns at once; poll guiding_status until it reports guiding "
      "and not settling. The mount must be tracking.",
      {"settle": _SETTLE, "recalibrate": B("Discard the calibration and redo it", False)},
      plugins=("guider", "phd2", "guide_simulator"))
async def guiding_start(ctx: ToolContext, args: dict[str, Any]) -> Any:
    pid = _guider_plugin(ctx)
    settle = args.get("settle") or {}
    body: Any = settle if pid == "guide_simulator" else {"settle": settle, "recalibrate": bool(args.get("recalibrate"))}
    await ctx.api.post(f"/plugins/{pid}/guide", body, timeout=120)
    return "guiding requested"


@tool("guiding_stop", "Stop guiding. Do this before slewing or flipping.", idempotent=True,
      plugins=("guider", "phd2", "guide_simulator"))
async def guiding_stop(ctx: ToolContext, args: dict[str, Any]) -> Any:
    await ctx.api.post(f"/plugins/{_guider_plugin(ctx)}/stop")
    return "stopped"


@tool("guiding_dither", "Nudge the guide star by a few pixels and wait for the guider to settle (between frames).",
      {"pixels": N("Dither size in guide pixels", default=3), "ra_only": B("RA only", False), "settle": _SETTLE},
      plugins=("guider", "phd2", "guide_simulator"))
async def guiding_dither(ctx: ToolContext, args: dict[str, Any]) -> Any:
    body = _drop({"pixels": args.get("pixels"), "ra_only": args.get("ra_only"), "settle": args.get("settle")})
    await ctx.api.post(f"/plugins/{_guider_plugin(ctx)}/dither", body, timeout=180)
    return "dithered"


# ── sequencer ─────────────────────────────────────────────────────────────────

def _schema_closure(spec: dict[str, Any], root: str) -> dict[str, Any]:
    schemas = spec.get("components", {}).get("schemas", {})
    seen: dict[str, Any] = {}
    todo = [root]
    while todo:
        name = todo.pop()
        if name in seen or name not in schemas:
            continue
        seen[name] = schemas[name]
        todo.extend(r.rsplit("/", 1)[-1] for r in _refs(schemas[name]))
    return seen


def _refs(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref" and isinstance(v, str):
                yield v
            else:
                yield from _refs(v)
    elif isinstance(node, list):
        for v in node:
            yield from _refs(v)


@tool("sequencer_task_schema",
      "JSON schema of a sequencer task (target, lanes of exposures, slew/centre/guide/dither options). "
      "Read it before sequencer_add_task.", read_only=True, plugins=("sequencer",))
async def sequencer_task_schema(ctx: ToolContext, args: dict[str, Any]) -> Any:
    spec = await ctx.api.get("/openapi.json")
    closure = _schema_closure(spec, "ImagingTask")
    if "ImagingTask" not in closure:
        raise ToolError("The task schema is not published by this server")
    return {"root": "#/components/schemas/ImagingTask", "components": {"schemas": closure}}


@tool("sequencer_status", "What the sequencer is doing: run state, activity, current task, progress, ETA, stalls.",
      read_only=True, plugins=("sequencer",))
async def sequencer_status(ctx: ToolContext, args: dict[str, Any]) -> Any:
    return await ctx.api.get("/plugins/sequencer/status")


@tool("sequencer_queue", "The task queue with each task's progress.", read_only=True, plugins=("sequencer",))
async def sequencer_queue(ctx: ToolContext, args: dict[str, Any]) -> Any:
    return await ctx.api.get("/plugins/sequencer/queue")


@tool("sequencer_add_task",
      "Append an imaging task to the queue. Shape: see sequencer_task_schema; the server validates it and says "
      "what is wrong. Nothing runs until sequencer_start.",
      {"task": O("An ImagingTask object"), "position": I("Insert at this index; default the end")},
      ("task",), plugins=("sequencer",))
async def sequencer_add_task(ctx: ToolContext, args: dict[str, Any]) -> Any:
    if not isinstance(args["task"], dict):
        raise ToolError("task must be an object")
    return await ctx.api.post("/plugins/sequencer/queue", args["task"], params={"position": args.get("position")})


@tool("sequencer_remove_task", "Remove one task from the queue.",
      {"task_id": S("Task id from sequencer_queue")}, ("task_id",), destructive=True, plugins=("sequencer",))
async def sequencer_remove_task(ctx: ToolContext, args: dict[str, Any]) -> Any:
    await ctx.api.delete(f"/plugins/sequencer/queue/{safe_id(args['task_id'], 'task_id')}")
    return "removed"


@tool("sequencer_preflight",
      "Check the queue can run now (devices connected, target reachable, …) and list errors and warnings. "
      "Run it before sequencer_start.",
      {"task_ids": {"type": "array", "items": {"type": "string"}, "description": "Only these tasks; default all"}},
      read_only=True, plugins=("sequencer",))
async def sequencer_preflight(ctx: ToolContext, args: dict[str, Any]) -> Any:
    return await ctx.api.post("/plugins/sequencer/preflight", _drop(args))


@tool("sequencer_start",
      "Start the queue: the sequencer slews, centres, guides, focuses and images unattended. Returns at once; "
      "follow it with sequencer_status. Run sequencer_preflight first.",
      {"from_task": S("Start at this task id"),
       "only": {"type": "array", "items": {"type": "string"}, "description": "Run only these task ids"}},
      destructive=True, plugins=("sequencer",))
async def sequencer_start(ctx: ToolContext, args: dict[str, Any]) -> Any:
    await ctx.api.post("/plugins/sequencer/start", {**_drop(args), "actor": "mcp"})
    return "started"


@tool("sequencer_pause", "Pause the run at the end of the current frame (or 'task' boundary); resume later.",
      {"when": S("Boundary: frame (default), task or now", enum=["frame", "task", "now"])},
      idempotent=True, plugins=("sequencer",))
async def sequencer_pause(ctx: ToolContext, args: dict[str, Any]) -> Any:
    await ctx.api.post("/plugins/sequencer/pause", {"actor": "mcp"}, params={"when": args.get("when")})
    return "pause requested"


@tool("sequencer_resume", "Resume a paused run.", idempotent=True, plugins=("sequencer",))
async def sequencer_resume(ctx: ToolContext, args: dict[str, Any]) -> Any:
    await ctx.api.post("/plugins/sequencer/resume", {"actor": "mcp"})
    return "resumed"


@tool("sequencer_stop", "End the run at the end of the current frame (or task boundary). Progress is kept.",
      {"when": S("Boundary: frame (default), task or now", enum=["frame", "task", "now"]),
       "reason": S("Why, for the session journal")},
      idempotent=True, plugins=("sequencer",))
async def sequencer_stop(ctx: ToolContext, args: dict[str, Any]) -> Any:
    await ctx.api.post("/plugins/sequencer/stop", {"actor": "mcp", "reason": args.get("reason")},
                       params={"when": args.get("when")})
    return "stop requested"


# ── safety ────────────────────────────────────────────────────────────────────

@tool("emergency_stop",
      "Halt everything that moves or exposes: stop all mounts, halt all cameras and focusers, stop guiding, "
      "abort autofocus and centering, stop the sequencer immediately. Use it if something looks wrong.",
      idempotent=True)
async def emergency_stop(ctx: ToolContext, args: dict[str, Any]) -> Any:
    api = ctx.api
    devices = await api.get("/devices/connected")
    acts: dict[str, Awaitable[Any]] = {}
    for d in devices:
        dev, kind = safe_id(d["device_id"]), d.get("kind")
        if kind == "mount":
            acts[f"mount_stop {dev}"] = api.post(f"/mount/{dev}/stop")
        elif kind == "camera":
            acts[f"camera_halt {dev}"] = api.post(f"/imager/{dev}/halt")
        elif kind == "focuser":
            acts[f"focuser_halt {dev}"] = api.post(f"/focuser/{dev}/halt")
    if ctx.plugin_enabled("sequencer"):
        acts["sequencer_stop"] = api.post("/plugins/sequencer/stop", {"actor": "mcp", "reason": "emergency stop"},
                                          params={"when": "now"})
    if ctx.plugin_enabled("autofocus"):
        acts["autofocus_abort"] = api.post("/plugins/autofocus/abort")
    if ctx.plugin_enabled("platesolve"):
        acts["platesolve_cancel_center"] = api.delete("/plugins/platesolve/center")
    for pid in ("guider", "phd2", "guide_simulator"):
        if ctx.plugin_enabled(pid):
            acts["guiding_stop"] = api.post(f"/plugins/{pid}/stop")
            break
    outcome = await asyncio.gather(*(_safe(c) for c in acts.values()))
    return {name: ("ok" if not isinstance(o, dict) or "error" not in o else o["error"])
            for name, o in zip(acts, outcome, strict=True)}
