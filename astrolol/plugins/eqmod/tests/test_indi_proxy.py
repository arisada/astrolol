"""The INDI mount proxy run as a real subprocess (as indiserver would), against a stub astrolol API."""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

PROXY = Path(__file__).resolve().parents[1] / "astrolol_indi_mount_proxy.py"
DEVICE = "astrolol Mount Proxy"


class _StubApi(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive, like uvicorn
    mount_connected = True
    mount_id = "m1"
    pulse_status = 204
    drop_after_response = False    # close silently, like an idle keep-alive timeout
    connections = 0
    pulses: list[tuple[str, int, float]] = []
    pulse_targets: list[str] = []
    status = {"ra_jnow": 5.5, "dec_jnow": 22.25, "pier_side": "West", "is_slewing": False}

    def setup(self) -> None:
        super().setup()
        type(self).connections += 1

    def log_message(self, *args) -> None:
        pass

    def end_headers(self) -> None:
        super().end_headers()
        if self.drop_after_response:
            self.close_connection = True

    def _json(self, code: int, body) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        if self.path == "/devices/connected":
            devices = [{"device_id": self.mount_id, "kind": "mount", "state": "connected"}] if self.mount_connected else []
            self._json(200, devices)
        elif self.path == f"/mount/{self.mount_id}/status":
            self._json(200, self.status)
        else:
            self._json(404, {"detail": "not found"})

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.startswith("/mount/") and self.path.endswith("/pulse_guide"):
            target = self.path.split("/")[2]
            if target != self.mount_id:
                self._json(404, {"detail": f"No connected device with id '{target}'."})
                return
            time.sleep(body["duration_ms"] / 1000.0)
            type(self).pulses.append((body["direction"], body["duration_ms"], time.monotonic()))
            type(self).pulse_targets.append(target)
            if self.pulse_status == 204:
                self.send_response(204)
                self.end_headers()
            else:
                self._json(self.pulse_status, {"detail": "Cannot guide: the mount is parked"})
        else:
            self._json(404, {"detail": "not found"})


class _Proxy:
    def __init__(self, api_url: str) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, str(PROXY), "--api", api_url],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        self.lines: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.proc.stdout:  # type: ignore[union-attr]
            self.lines.put((time.monotonic(), ET.fromstring(line)))

    def send(self, xml: str) -> None:
        self.proc.stdin.write(xml.encode())  # type: ignore[union-attr]
        self.proc.stdin.flush()  # type: ignore[union-attr]

    def wait_for(self, pred, timeout: float = 5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                t, el = self.lines.get(timeout=deadline - time.monotonic())
            except queue.Empty:
                break
            if pred(el):
                return t, el
        raise AssertionError("expected INDI element not received")

    def close(self) -> None:
        self.proc.stdin.close()  # type: ignore[union-attr]
        self.proc.wait(timeout=5)


def _named(tag: str, name: str, state: str | None = None):
    return lambda el: el.tag == tag and el.get("name") == name and (state is None or el.get("state") == state)


def _values(el: ET.Element) -> dict[str, str]:
    return {c.get("name"): (c.text or "").strip() for c in el}


@pytest.fixture
def api():
    _StubApi.mount_connected = True
    _StubApi.mount_id = "m1"
    _StubApi.pulse_status = 204
    _StubApi.drop_after_response = False
    _StubApi.connections = 0
    _StubApi.pulses = []
    _StubApi.pulse_targets = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubApi)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def proxy(api):
    p = _Proxy(api)
    yield p
    p.close()


def test_defines_its_properties_on_get_properties(proxy: _Proxy) -> None:
    proxy.send('<getProperties version="1.7"/>')
    names = set()
    for _ in range(6):
        _, el = proxy.wait_for(lambda el: el.tag.startswith("def"))
        assert el.get("device") == DEVICE
        names.add(el.get("name"))
    assert names == {
        "CONNECTION", "DRIVER_INFO", "EQUATORIAL_EOD_COORD", "TELESCOPE_PIER_SIDE",
        "TELESCOPE_TIMED_GUIDE_NS", "TELESCOPE_TIMED_GUIDE_WE",
    }


def test_driver_info_says_it_is_a_proxy(proxy: _Proxy) -> None:
    proxy.send(f'<getProperties version="1.7" device="{DEVICE}" name="DRIVER_INFO"/>')
    _, el = proxy.wait_for(_named("defTextVector", "DRIVER_INFO"))
    info = _values(el)
    assert info["DRIVER_EXEC"] == "astrolol-indi-mount-proxy"
    assert "not a mount driver" in info["DRIVER_NAME"]
    assert info["DRIVER_INTERFACE"] == "5"


def test_ignores_other_devices(proxy: _Proxy) -> None:
    proxy.send('<getProperties version="1.7" device="Telescope Simulator"/>')
    proxy.send(f'<getProperties version="1.7" device="{DEVICE}" name="CONNECTION"/>')
    _, el = proxy.wait_for(lambda el: el.tag.startswith("def"))
    assert el.get("name") == "CONNECTION"


def test_connect_requires_a_mount_in_astrolol(proxy: _Proxy) -> None:
    connect = f'<newSwitchVector device="{DEVICE}" name="CONNECTION"><oneSwitch name="CONNECT">On</oneSwitch></newSwitchVector>'
    _StubApi.mount_connected = False
    proxy.send(connect)
    _, el = proxy.wait_for(_named("setSwitchVector", "CONNECTION"))
    assert el.get("state") == "Alert" and _values(el)["CONNECT"] == "Off"
    _StubApi.mount_connected = True
    proxy.send(connect)
    _, el = proxy.wait_for(_named("setSwitchVector", "CONNECTION"))
    assert el.get("state") == "Ok" and _values(el)["CONNECT"] == "On"


@pytest.mark.parametrize("vector,member,direction", [
    ("TELESCOPE_TIMED_GUIDE_WE", "TIMED_GUIDE_W", "W"),
    ("TELESCOPE_TIMED_GUIDE_WE", "TIMED_GUIDE_E", "E"),
    ("TELESCOPE_TIMED_GUIDE_NS", "TIMED_GUIDE_N", "N"),
    ("TELESCOPE_TIMED_GUIDE_NS", "TIMED_GUIDE_S", "S"),
])
def test_pulse_is_busy_until_astrolol_finishes_it(proxy: _Proxy, vector: str, member: str, direction: str) -> None:
    other = {"TIMED_GUIDE_W": "TIMED_GUIDE_E", "TIMED_GUIDE_E": "TIMED_GUIDE_W",
             "TIMED_GUIDE_N": "TIMED_GUIDE_S", "TIMED_GUIDE_S": "TIMED_GUIDE_N"}[member]
    proxy.send(f'<newNumberVector device="{DEVICE}" name="{vector}">'
               f'<oneNumber name="{member}">200</oneNumber><oneNumber name="{other}">0</oneNumber></newNumberVector>')
    busy_at, _ = proxy.wait_for(_named("setNumberVector", vector, "Busy"))
    done_at, done = proxy.wait_for(_named("setNumberVector", vector, "Ok"))
    assert done_at - busy_at >= 0.19
    assert _StubApi.pulses[0][:2] == (direction, 200)
    assert set(_values(done).values()) == {"0"}


def test_refused_pulse_reports_alert_with_the_reason(proxy: _Proxy) -> None:
    _StubApi.pulse_status = 409
    proxy.send(f'<newNumberVector device="{DEVICE}" name="TELESCOPE_TIMED_GUIDE_NS">'
               f'<oneNumber name="TIMED_GUIDE_N">50</oneNumber><oneNumber name="TIMED_GUIDE_S">0</oneNumber></newNumberVector>')
    proxy.wait_for(_named("setNumberVector", "TELESCOPE_TIMED_GUIDE_NS", "Alert"))
    _, msg = proxy.wait_for(lambda el: el.tag == "message")
    assert "parked" in msg.get("message")


def test_publishes_position_and_pier_side_without_being_connected(proxy: _Proxy) -> None:
    """Snooping drivers (e.g. the CCD simulator) must get coordinates even if no client connects."""
    _, coord = proxy.wait_for(_named("setNumberVector", "EQUATORIAL_EOD_COORD", "Ok"))
    assert _values(coord) == {"RA": "5.5", "DEC": "22.25"}
    _, pier = proxy.wait_for(_named("setSwitchVector", "TELESCOPE_PIER_SIDE"))
    assert _values(pier) == {"PIER_WEST": "On", "PIER_EAST": "Off"}


def test_exits_when_indiserver_closes_stdin(api) -> None:
    p = _Proxy(api)
    p.proc.stdin.close()  # type: ignore[union-attr]
    assert p.proc.wait(timeout=5) == 0


def test_survives_astrolol_being_down(proxy: _Proxy) -> None:
    unreachable = _Proxy("http://127.0.0.1:9")  # discard port: nothing listens
    try:
        _, coord = unreachable.wait_for(_named("setNumberVector", "EQUATORIAL_EOD_COORD"))
        assert coord.get("state") == "Alert"
        unreachable.send(f'<newNumberVector device="{DEVICE}" name="TELESCOPE_TIMED_GUIDE_WE">'
                         f'<oneNumber name="TIMED_GUIDE_W">50</oneNumber></newNumberVector>')
        unreachable.wait_for(_named("setNumberVector", "TELESCOPE_TIMED_GUIDE_WE", "Alert"))
        assert unreachable.proc.poll() is None
    finally:
        unreachable.close()


def test_device_name_is_hidden_by_astrolols_own_indi_client() -> None:
    from astrolol.devices.indi.client import is_astrolol_shim
    from astrolol.plugins.eqmod.astrolol_indi_mount_proxy import DEVICE as PROXY_DEVICE

    assert is_astrolol_shim(PROXY_DEVICE)


def _pulse(proxy: _Proxy, member: str = "TIMED_GUIDE_W", ms: int = 30) -> ET.Element:
    vector = "TELESCOPE_TIMED_GUIDE_WE" if member in ("TIMED_GUIDE_W", "TIMED_GUIDE_E") else "TELESCOPE_TIMED_GUIDE_NS"
    proxy.send(f'<newNumberVector device="{DEVICE}" name="{vector}"><oneNumber name="{member}">{ms}</oneNumber></newNumberVector>')
    _, el = proxy.wait_for(lambda el: el.get("name") == vector and el.get("state") not in (None, "Busy"))
    return el


def test_reuses_one_connection_for_pulses_and_polling(proxy: _Proxy) -> None:
    proxy.wait_for(_named("setNumberVector", "EQUATORIAL_EOD_COORD", "Ok"))  # first poll done
    for member in ("TIMED_GUIDE_W", "TIMED_GUIDE_E", "TIMED_GUIDE_N", "TIMED_GUIDE_S"):
        assert _pulse(proxy, member).get("state") == "Ok"
    proxy.wait_for(_named("setNumberVector", "EQUATORIAL_EOD_COORD", "Ok"))  # another poll
    assert _StubApi.connections == 1


def test_pulses_reuse_the_polled_mount_id(proxy: _Proxy) -> None:
    proxy.wait_for(_named("setNumberVector", "EQUATORIAL_EOD_COORD", "Ok"))
    before = _StubApi.connections
    for _ in range(3):
        _pulse(proxy)
    assert _StubApi.pulse_targets == ["m1", "m1", "m1"]
    assert _StubApi.connections == before


def test_recovers_when_astrolol_drops_the_idle_connection(proxy: _Proxy) -> None:
    """uvicorn closes idle keep-alive connections; the next request must go through, once."""
    _StubApi.drop_after_response = True
    proxy.wait_for(_named("setNumberVector", "EQUATORIAL_EOD_COORD", "Ok"))
    for _ in range(3):
        assert _pulse(proxy).get("state") == "Ok"
    assert len(_StubApi.pulses) == 3  # every pulse executed exactly once
    assert _StubApi.connections > 1


def test_pulse_follows_a_mount_reconnected_under_another_id(proxy: _Proxy) -> None:
    proxy.wait_for(_named("setNumberVector", "EQUATORIAL_EOD_COORD", "Ok"))  # caches m1
    _StubApi.mount_id = "m2"
    assert _pulse(proxy).get("state") == "Ok"
    assert _StubApi.pulse_targets == ["m2"]
