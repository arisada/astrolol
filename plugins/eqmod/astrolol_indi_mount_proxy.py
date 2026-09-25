#!/usr/bin/env python3
"""astrolol INDI mount proxy — NOT a real mount driver.

indiserver runs this as a local driver (INDI XML on stdin/stdout). It shows the mount
astrolol is connected to as an INDI telescope named "astrolol Mount Proxy": guide pulses
are relayed to astrolol's REST API, and the mount's position and pier side are published
for PHD2 and for INDI drivers that snoop a telescope (e.g. the CCD simulator).

Standard library only, so it runs from whatever Python astrolol uses.
"""
from __future__ import annotations

import argparse
import asyncio
import http.client
import json
import logging
import sys
import threading
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, BinaryIO

DEVICE = "astrolol Mount Proxy"
EXECUTABLE = "astrolol-indi-mount-proxy"
VERSION = "1.0"
POLL_INTERVAL = 2.0     # seconds between position refreshes
MAX_PULSE_MS = 10_000
GUIDE_VECTORS = {
    "TELESCOPE_TIMED_GUIDE_NS": ("TIMED_GUIDE_N", "TIMED_GUIDE_S"),
    "TELESCOPE_TIMED_GUIDE_WE": ("TIMED_GUIDE_W", "TIMED_GUIDE_E"),
}

log = logging.getLogger(EXECUTABLE)


class ProxyError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status  # HTTP status when astrolol answered, None when unreachable


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


class AstrololApi:
    """One persistent HTTP/1.1 connection to astrolol, shared by all requests (one at a time)."""

    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/")
        parts = urllib.parse.urlsplit(self.base)
        self._https = parts.scheme == "https"
        self._host = parts.hostname or "127.0.0.1"
        self._port = parts.port
        self._prefix = parts.path
        self._conn: http.client.HTTPConnection | None = None
        self._lock = threading.Lock()  # requests run in worker threads

    def _close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _request(self, method: str, path: str, body: Any = None, timeout: float = 5.0) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        with self._lock:
            while True:
                reused = self._conn is not None
                if self._conn is None:
                    cls = http.client.HTTPSConnection if self._https else http.client.HTTPConnection
                    self._conn = cls(self._host, self._port, timeout=timeout)
                self._conn.timeout = timeout
                if self._conn.sock is not None:
                    self._conn.sock.settimeout(timeout)
                try:
                    self._conn.request(method, self._prefix + path, body=data, headers=headers)
                    resp = self._conn.getresponse()
                    raw = resp.read()
                except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError) as exc:
                    self._close()
                    if reused:
                        # astrolol dropped the idle keep-alive connection before seeing this
                        # request: resend once on a fresh one.
                        continue
                    raise ProxyError(f"astrolol unreachable at {self.base}: {exc}") from exc
                except (OSError, http.client.HTTPException) as exc:
                    self._close()
                    raise ProxyError(f"astrolol unreachable at {self.base}: {exc}") from exc
                if resp.will_close:
                    self._close()
                break
        if resp.status >= 400:
            try:
                detail = json.loads(raw).get("detail", resp.reason)
            except (ValueError, AttributeError):
                detail = resp.reason
            raise ProxyError(f"astrolol refused: {detail}", status=resp.status)
        return json.loads(raw) if raw else None

    async def call(self, method: str, path: str, body: Any = None, timeout: float = 5.0) -> Any:
        return await asyncio.to_thread(self._request, method, path, body, timeout)

    async def mount_id(self) -> str | None:
        devices = await self.call("GET", "/devices/connected")
        for d in devices or []:
            if d.get("kind") == "mount" and d.get("state") == "connected":
                return d["device_id"]
        return None

    async def status(self, mount_id: str) -> dict[str, Any]:
        return await self.call("GET", f"/mount/{mount_id}/status")

    async def pulse(self, mount_id: str, direction: str, duration_ms: int) -> None:
        await self.call(
            "POST", f"/mount/{mount_id}/pulse_guide",
            {"direction": direction, "duration_ms": duration_ms},
            timeout=duration_ms / 1000.0 + 10.0,
        )


def _element(tag: str, attrs: dict[str, str], children: list[ET.Element] | None = None) -> ET.Element:
    el = ET.Element(tag, attrs)
    for child in children or []:
        el.append(child)
    return el


def _member(tag: str, name: str, value: str, **attrs: str) -> ET.Element:
    el = ET.Element(tag, {"name": name, **attrs})
    el.text = value
    return el


class MountProxy:
    def __init__(self, api: AstrololApi, out: BinaryIO) -> None:
        self.api = api
        self.out = out
        self.connected = False
        self.ra = 0.0
        self.dec = 0.0
        self.coord_state = "Idle"
        self.pier_side: str | None = None
        self.mount_id: str | None = None  # refreshed by the position poll, reused by pulses
        self._tasks: set[asyncio.Task] = set()

    async def _refresh_mount_id(self) -> str | None:
        self.mount_id = await self.api.mount_id()
        return self.mount_id

    # --- Output ---

    def send(self, el: ET.Element) -> None:
        self.out.write(ET.tostring(el) + b"\n")
        self.out.flush()

    def message(self, text: str) -> None:
        self.send(_element("message", {"device": DEVICE, "timestamp": _timestamp(), "message": text}))

    def _vector(self, kind: str, name: str, state: str, members: list[ET.Element], **attrs: str) -> ET.Element:
        return _element(kind, {"device": DEVICE, "name": name, "state": state, "timestamp": _timestamp(), **attrs}, members)

    def define_all(self, name: str | None = None) -> None:
        on, off = ("On", "Off") if self.connected else ("Off", "On")
        defs = {
            "CONNECTION": self._vector("defSwitchVector", "CONNECTION", "Ok" if self.connected else "Idle", [
                _member("defSwitch", "CONNECT", on, label="Connect"),
                _member("defSwitch", "DISCONNECT", off, label="Disconnect"),
            ], label="Connection", group="Main Control", perm="rw", rule="OneOfMany", timeout="0"),
            "DRIVER_INFO": self._vector("defTextVector", "DRIVER_INFO", "Idle", [
                _member("defText", "DRIVER_NAME", "astrolol Mount Proxy (relays to the astrolol REST API; not a mount driver)", label="Name"),
                _member("defText", "DRIVER_EXEC", EXECUTABLE, label="Exec"),
                _member("defText", "DRIVER_VERSION", VERSION, label="Version"),
                _member("defText", "DRIVER_INTERFACE", "5", label="Interface"),  # telescope | guider
            ], label="Driver Info", group="General Info", perm="ro"),
            "EQUATORIAL_EOD_COORD": self._coord_vector("defNumberVector"),
            "TELESCOPE_PIER_SIDE": self._pier_vector("defSwitchVector"),
        }
        for vector, (north_or_west, south_or_east) in GUIDE_VECTORS.items():
            defs[vector] = self._vector("defNumberVector", vector, "Idle", [
                _member("defNumber", north_or_west, "0", label=north_or_west[-1] + " (ms)", format="%.0f", min="0", max=str(MAX_PULSE_MS), step="1"),
                _member("defNumber", south_or_east, "0", label=south_or_east[-1] + " (ms)", format="%.0f", min="0", max=str(MAX_PULSE_MS), step="1"),
            ], label="Guide " + vector[-2:], group="Guide", perm="rw", timeout="0")
        for vector_name, el in defs.items():
            if name is None or name == vector_name:
                self.send(el)

    def _coord_vector(self, kind: str) -> ET.Element:
        member = "defNumber" if kind.startswith("def") else "oneNumber"
        extra = {"label": "Eq. Coordinates", "group": "Main Control", "perm": "ro", "timeout": "0"} if kind.startswith("def") else {}
        ra_attrs = {"label": "RA (hh:mm:ss)", "format": "%010.6m", "min": "0", "max": "24", "step": "0"} if member == "defNumber" else {}
        dec_attrs = {"label": "DEC (dd:mm:ss)", "format": "%010.6m", "min": "-90", "max": "90", "step": "0"} if member == "defNumber" else {}
        return self._vector(kind, "EQUATORIAL_EOD_COORD", self.coord_state, [
            _member(member, "RA", repr(self.ra), **ra_attrs),
            _member(member, "DEC", repr(self.dec), **dec_attrs),
        ], **extra)

    def _pier_vector(self, kind: str) -> ET.Element:
        member = "defSwitch" if kind.startswith("def") else "oneSwitch"
        extra = {"label": "Pier Side", "group": "Main Control", "perm": "ro", "rule": "AtMostOne", "timeout": "0"} if kind.startswith("def") else {}
        east = "On" if self.pier_side == "East" else "Off"
        west = "On" if self.pier_side == "West" else "Off"
        state = "Ok" if self.pier_side else "Idle"
        return self._vector(kind, "TELESCOPE_PIER_SIDE", state, [
            _member(member, "PIER_WEST", west, **({"label": "West (pointing east)"} if member == "defSwitch" else {})),
            _member(member, "PIER_EAST", east, **({"label": "East (pointing west)"} if member == "defSwitch" else {})),
        ], **extra)

    # --- Input ---

    async def handle(self, el: ET.Element) -> None:
        device = el.get("device")
        if el.tag == "getProperties":
            if device in (None, "", "*", DEVICE):
                self.define_all(el.get("name"))
            return
        if device != DEVICE:
            return
        name = el.get("name")
        values = {child.get("name"): (child.text or "").strip() for child in el}
        if el.tag == "newSwitchVector" and name == "CONNECTION":
            await self._connect(values.get("CONNECT") == "On")
        elif el.tag == "newNumberVector" and name in GUIDE_VECTORS:
            task = asyncio.get_running_loop().create_task(self._pulse(name, values))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        elif el.tag == "newNumberVector" and name == "EQUATORIAL_EOD_COORD":
            self.send(self._coord_vector("setNumberVector"))
            self.message("Position is read-only here: slew from astrolol")

    async def _connect(self, want: bool) -> None:
        if want:
            try:
                if await self._refresh_mount_id() is None:
                    raise ProxyError("astrolol has no mount connected")
                self.connected = True
                state = "Ok"
            except ProxyError as exc:
                self.connected = False
                state = "Alert"
                self.message(f"Cannot connect: {exc}")
        else:
            self.connected = False
            state = "Idle"
        on, off = ("On", "Off") if self.connected else ("Off", "On")
        self.send(self._vector("setSwitchVector", "CONNECTION", state, [
            _member("oneSwitch", "CONNECT", on), _member("oneSwitch", "DISCONNECT", off),
        ]))

    async def _pulse(self, vector: str, values: dict[str, str]) -> None:
        first, second = GUIDE_VECTORS[vector]

        def reply(state: str, v1: float = 0.0, v2: float = 0.0) -> None:
            self.send(self._vector("setNumberVector", vector, state, [
                _member("oneNumber", first, f"{v1:g}"), _member("oneNumber", second, f"{v2:g}"),
            ]))

        try:
            v1, v2 = float(values.get(first) or 0), float(values.get(second) or 0)
        except ValueError:
            reply("Alert")
            return
        if v1 <= 0 and v2 <= 0:
            reply("Ok")
            return
        direction, ms = (first[-1], v1) if v1 > 0 else (second[-1], v2)
        reply("Busy", v1, v2)  # PHD2 waits for a non-Busy state to know the pulse is over
        try:
            duration = int(round(min(ms, MAX_PULSE_MS)))
            mount_id = self.mount_id or await self._refresh_mount_id()
            if mount_id is None:
                raise ProxyError("astrolol has no mount connected")
            try:
                await self.api.pulse(mount_id, direction, duration)
            except ProxyError as exc:
                if exc.status != 404:
                    raise
                # The mount was reconnected under another id since the last poll.
                mount_id = await self._refresh_mount_id()
                if mount_id is None:
                    raise ProxyError("astrolol has no mount connected") from exc
                await self.api.pulse(mount_id, direction, duration)
            reply("Ok")
        except ProxyError as exc:
            log.warning("pulse %s %sms failed: %s", direction, ms, exc)
            reply("Alert")
            self.message(f"Guide pulse {direction} {ms:.0f} ms failed: {exc}")

    # --- Position feed ---

    async def poll_position(self) -> None:
        while True:
            try:
                mount_id = await self._refresh_mount_id()
                if mount_id is None:
                    self.coord_state = "Alert"
                else:
                    st = await self.api.status(mount_id)
                    if st.get("ra_jnow") is None or st.get("dec_jnow") is None:
                        self.coord_state = "Alert"
                    else:
                        self.ra, self.dec = float(st["ra_jnow"]), float(st["dec_jnow"])
                        self.coord_state = "Busy" if st.get("is_slewing") else "Ok"
                    self.pier_side = st.get("pier_side")
            except ProxyError:
                self.coord_state = "Alert"
            self.send(self._coord_vector("setNumberVector"))
            if self.pier_side:
                self.send(self._pier_vector("setSwitchVector"))
            await asyncio.sleep(POLL_INTERVAL)

    # --- Main loop ---

    async def run(self, stream: BinaryIO) -> None:
        parser = ET.XMLPullParser(events=("start", "end"))
        parser.feed(b"<stream>")  # the INDI stream is a sequence of top-level elements
        root: ET.Element | None = None
        depth = 0
        poller = asyncio.get_running_loop().create_task(self.poll_position())
        try:
            while True:
                chunk = await asyncio.to_thread(stream.read1, 65536)
                if not chunk:
                    return  # indiserver closed our stdin
                parser.feed(chunk)
                for event, el in parser.read_events():
                    if event == "start":
                        if root is None:
                            root = el
                        depth += 1
                    else:
                        depth -= 1
                        if depth == 1:
                            await self.handle(el)
                            root.remove(el)  # type: ignore[union-attr]
        finally:
            poller.cancel()
            for task in list(self._tasks):
                task.cancel()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="astrolol base URL")
    args = parser.parse_args()
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format=f"{EXECUTABLE}: %(message)s")
    log.info("relaying to %s", args.api)
    asyncio.run(MountProxy(AstrololApi(args.api), sys.stdout.buffer).run(sys.stdin.buffer))


if __name__ == "__main__":
    main()
