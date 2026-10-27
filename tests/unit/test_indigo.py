"""INDIGO server support without an INDIGO server: catalog, device interfaces, driver loading.

tests/integration/test_api_indigo.py runs the same against a real one.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from astrolol.devices.indi import indigo
from astrolol.devices.indi.plugin import IndiConnectionManager


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

_DRIVER_LIST = '''\
"indigo_ccd_asi", "ZWO ASI Camera", 03000024
"indigo_ccd_simulator", "Camera Simulator", 0300002c
"indigo_wheel_sx", "Starlight Xpress Filter Wheel", 03000007
"indigo_mount_lx200", "LX200 Mount", 03000030
"indigo_aux_flipflat", "Alnitak Astrosystems FlipFlat", 0300000d
"indigo_aux_upb", "PegasusAstro Ultimate Powerbox", 03000010
"indigo_agent_imager", "Imager Agent", 03000050
'''


def test_catalog_kinds_groups_and_makers(tmp_path: Path) -> None:
    (tmp_path / "indigo_drivers").write_text(_DRIVER_LIST)
    entries = {e.executable: e for e in indigo.load_catalog([tmp_path])}
    assert "indigo_agent_imager" not in entries
    asi = entries["indigo_ccd_asi"]
    assert (asi.kind, asi.group, asi.manufacturer, asi.label) == ("camera", "CCDs", "ZWO", "ZWO ASI Camera")
    assert entries["indigo_ccd_simulator"].manufacturer == "Simulator"
    assert entries["indigo_wheel_sx"].manufacturer == "Starlight Xpress"
    assert entries["indigo_wheel_sx"].kind == "filter_wheel"
    assert entries["indigo_mount_lx200"].manufacturer == "Others"
    assert entries["indigo_aux_flipflat"].kind == "flat_panel"
    assert entries["indigo_aux_upb"].kind == "aux"


def test_catalog_merges_lists_and_keeps_the_first(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    (first / "indigo_drivers").write_text('"indigo_ccd_asi", "ZWO ASI Camera", 1\n')
    (second / "indigo_drivers").write_text('"indigo_ccd_asi", "Old label", 1\n')
    (second / "indigo_linux_drivers").write_text('"indigo_ccd_libcamera", "libcamera Camera", 1\n')
    entries = indigo.load_catalog([first, second, tmp_path / "missing"])
    # Sorted by kind, maker ("Others" for libcamera), label.
    assert [(e.executable, e.label) for e in entries] == [
        ("indigo_ccd_libcamera", "libcamera Camera"),
        ("indigo_ccd_asi", "ZWO ASI Camera"),
    ]


def test_catalog_dir_is_found_through_a_symlinked_binary(tmp_path: Path) -> None:
    prefix = tmp_path / "build"
    (prefix / "bin").mkdir(parents=True)
    binary = prefix / "bin" / "indigo_server"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    (tmp_path / "bin").mkdir()
    link = tmp_path / "bin" / "indigo_server"
    link.symlink_to(binary)
    dirs = indigo.catalog_dirs(str(link))
    assert dirs[0] == prefix / "share" / "indigo"
    assert Path("/usr/share/indigo") in dirs


def test_non_indigo_drivers_are_not_catalogued() -> None:
    assert indigo.driver_entry("indi_asi_ccd", "ZWO CCD") is None


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------

class _Member:
    def __init__(self, value: str, label: str = "") -> None:
        self.membervalue = value
        self.label = label


class _Vector:
    def __init__(self, state: str = "Ok", **members: _Member) -> None:
        self.state = state
        self.data = members

    def __getitem__(self, name: str) -> str:
        return self.data[name].membervalue


def _info(driver: str, interface: int) -> _Vector:
    return _Vector(DEVICE_DRIVER=_Member(driver), DRIVER_INTERFACE=_Member(str(interface)))


class _FakeClient:
    """The slice of IndiClient the INDIGO helpers read: devices and their vectors."""

    def __init__(self, devices: dict[str, dict[str, _Vector]]) -> None:
        self.devices = devices
        self.texts: list[tuple[str, str, dict]] = []
        self._cond: asyncio.Condition | None = None

    def list_devices(self) -> list[str]:
        return list(self.devices)

    def _get_vector(self, device: str, prop: str):  # noqa: ANN202
        return self.devices.get(device, {}).get(prop)

    def _vector_state(self, device: str, prop: str) -> str | None:
        v = self._get_vector(device, prop)
        return None if v is None else v.state

    def get_switch_state_nowait(self, device: str, prop: str, element: str) -> bool | None:
        v = self._get_vector(device, prop)
        if v is None or element not in v.data:
            return None
        return v[element] == "On"

    async def wait_for_property(self, device: str, prop: str, timeout: float = 10.0):  # noqa: ANN201
        return self._get_vector(device, prop)

    async def set_text(self, device: str, prop: str, values: dict) -> None:
        self.texts.append((device, prop, values))
        if prop == "LOAD":
            self.on_load(values["DRIVER"])

    def on_load(self, driver: str) -> None:
        pass

    async def _wait_cond(self, predicate, timeout: float) -> None:  # noqa: ANN001
        if not predicate():
            raise TimeoutError("not met")


_SIMULATOR = {
    "CCD Imager Simulator": {"DRIVER_INFO": _info("indigo_ccd_simulator", indigo.INTERFACE_CCD)},
    "CCD Imager Simulator (wheel)": {"DRIVER_INFO": _info("indigo_ccd_simulator", indigo.INTERFACE_WHEEL)},
    "CCD Imager Simulator (focuser)": {"DRIVER_INFO": _info("indigo_ccd_simulator", indigo.INTERFACE_FOCUSER)},
    "CCD Guider Simulator": {"DRIVER_INFO": _info("indigo_ccd_simulator", indigo.INTERFACE_CCD)},
    "CCD Guider Simulator (guider)": {"DRIVER_INFO": _info("indigo_ccd_simulator", indigo.INTERFACE_GUIDER)},
    "Mount Simulator": {"DRIVER_INFO": _info("indigo_mount_simulator", indigo.INTERFACE_MOUNT)},
    "Flat Panel Simulator": {"DRIVER_INFO": _info("indigo_aux_simulator", 3178496)},
}


@pytest.mark.parametrize("interface, kinds", [
    (indigo.INTERFACE_CCD, ["camera"]),
    (indigo.INTERFACE_GUIDER, []),
    (indigo.INTERFACE_AO, []),
    (indigo.INTERFACE_CCD | indigo.INTERFACE_GUIDER, ["camera"]),
    (3178496, ["flat_panel"]),          # INDIGO's flat panel simulator: light box + dust cap
    (indigo.INTERFACE_AUX, []),         # a powerbox, a weather station
])
def test_kinds_of_interface(interface: int, kinds: list[str]) -> None:
    assert indigo.kinds_of_interface(interface) == kinds


def test_devices_of_a_driver_leave_out_guide_outputs() -> None:
    client = _FakeClient(_SIMULATOR)
    assert indigo.devices_of_driver(client, "indigo_ccd_simulator") == [  # type: ignore[arg-type]
        "CCD Imager Simulator", "CCD Imager Simulator (wheel)",
        "CCD Imager Simulator (focuser)", "CCD Guider Simulator",
    ]


def test_only_devices_of_the_wanted_kind_are_offered() -> None:
    client = _FakeClient(_SIMULATOR)
    devices = indigo.devices_of_driver(client, "indigo_ccd_simulator")  # type: ignore[arg-type]
    assert indigo.devices_for_kind(client, devices, "camera") == [  # type: ignore[arg-type]
        "CCD Imager Simulator", "CCD Guider Simulator",
    ]
    # A driver whose devices are of another kind: all of them, rather than none.
    assert indigo.devices_for_kind(client, devices, "rotator") == devices  # type: ignore[arg-type]


def test_companions_are_the_devices_named_after_it() -> None:
    client = _FakeClient(_SIMULATOR)
    assert indigo.companion_devices(client, "CCD Imager Simulator") == [  # type: ignore[arg-type]
        ("filter_wheel", "CCD Imager Simulator (wheel)"),
        ("focuser", "CCD Imager Simulator (focuser)"),
    ]
    assert indigo.companion_devices(client, "CCD Guider Simulator") == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Driver loading
# ---------------------------------------------------------------------------

def _server_device(loaded: dict[str, str]) -> dict[str, _Vector]:
    return {
        "LOAD": _Vector(DRIVER=_Member("")),
        "UNLOAD": _Vector(DRIVER=_Member("")),
        "DRIVERS": _Vector(**{name: _Member(state) for name, state in loaded.items()}),
    }


def _indigo_server(client: _FakeClient) -> indigo.IndigoServer:
    return indigo.IndigoServer(client, manage=False)  # type: ignore[arg-type]


async def test_load_sends_load_and_waits_for_the_driver() -> None:
    client = _FakeClient({"Server": _server_device({"indigo_mount_simulator": "Off"})})
    client.on_load = lambda d: setattr(client.devices["Server"]["DRIVERS"].data[d], "membervalue", "On")
    await _indigo_server(client).load_driver("indigo_mount_simulator")
    assert client.texts == [("Server", "LOAD", {"DRIVER": "indigo_mount_simulator"})]


async def test_a_loaded_driver_is_not_loaded_again() -> None:
    client = _FakeClient({"Server": _server_device({"indigo_mount_simulator": "On"})})
    await _indigo_server(client).load_driver("indigo_mount_simulator")
    assert client.texts == []


async def test_a_refused_driver_raises() -> None:
    client = _FakeClient({"Server": _server_device({"indigo_ccd_asi": "Off"})})
    client.on_load = lambda d: setattr(client.devices["Server"]["LOAD"], "state", "Alert")
    with pytest.raises(RuntimeError):
        await _indigo_server(client).load_driver("indigo_ccd_asi")


async def test_an_indi_driver_is_refused_without_asking_the_server() -> None:
    client = _FakeClient({"Server": _server_device({})})
    with pytest.raises(ValueError):
        await _indigo_server(client).load_driver("indi_simulator_telescope")
    assert client.texts == []


async def test_unload_sends_unload() -> None:
    client = _FakeClient({"Server": _server_device({"indigo_ccd_asi": "On"})})
    await _indigo_server(client).unload_driver("indigo_ccd_asi")
    assert client.texts == [("Server", "UNLOAD", {"DRIVER": "indigo_ccd_asi"})]


async def test_a_managed_server_needs_the_binary(tmp_path: Path) -> None:
    server = indigo.IndigoServer(
        _FakeClient({}), manage=True, port=1, run_dir=tmp_path,  # type: ignore[arg-type]
        server_path=str(tmp_path / "no-such-indigo_server"),
    )
    with pytest.raises(RuntimeError, match="not found"):
        await server.start()


# ---------------------------------------------------------------------------
# The connection manager
# ---------------------------------------------------------------------------

class _CountingServer:
    def __init__(self) -> None:
        self.loaded: list[str] = []
        self.unloaded: list[str] = []

    async def load_driver(self, executable: str) -> None:
        self.loaded.append(executable)

    async def unload_driver(self, executable: str) -> None:
        self.unloaded.append(executable)


def _manager(tmp_path: Path) -> tuple[IndiConnectionManager, _CountingServer]:
    manager = IndiConnectionManager(run_dir=tmp_path)
    server = _CountingServer()
    manager._server = server  # type: ignore[assignment]
    return manager, server


async def test_a_driver_is_unloaded_when_its_last_device_goes(tmp_path: Path) -> None:
    manager, server = _manager(tmp_path)
    await manager.load_driver("indigo_ccd_simulator")   # the camera
    await manager.load_driver("indigo_ccd_simulator")   # its filter wheel
    await manager.unload_driver("indigo_ccd_simulator")
    assert server.unloaded == []
    await manager.unload_driver("indigo_ccd_simulator")
    assert server.unloaded == ["indigo_ccd_simulator"]


async def test_a_preview_load_is_not_a_user(tmp_path: Path) -> None:
    manager, server = _manager(tmp_path)
    await manager.preload_driver("indi_asi_ccd")        # "Load driver" in the wizard
    await manager.load_driver("indi_asi_ccd")           # the camera connects
    await manager.unload_driver("indi_asi_ccd")
    assert server.loaded == ["indi_asi_ccd", "indi_asi_ccd"]
    assert server.unloaded == ["indi_asi_ccd"]


def test_the_server_follows_the_setting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from astrolol.config.settings import settings
    from astrolol.devices.indi.server import IndiServer
    monkeypatch.setattr(settings, "indi_server_kind", "indigo")
    manager = IndiConnectionManager(run_dir=tmp_path)
    assert manager.server_kind == "indigo"
    assert isinstance(manager._server, indigo.IndigoServer)
    monkeypatch.setattr(settings, "indi_server_kind", "indi")
    assert isinstance(IndiConnectionManager(run_dir=tmp_path)._server, IndiServer)


async def test_indigo_roles_include_the_devices_named_after_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from astrolol.config.settings import settings
    monkeypatch.setattr(settings, "indi_server_kind", "indigo")
    manager = IndiConnectionManager(run_dir=tmp_path)
    devices = {name: dict(props) for name, props in _SIMULATOR.items()}
    devices["CCD Imager Simulator"]["CCD_EXPOSURE"] = _Vector()
    client = _FakeClient(devices)
    client.data = devices  # type: ignore[attr-defined]  # discover_roles counts properties here
    manager._client = client  # type: ignore[assignment]
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    assert await manager.discover_roles("CCD Imager Simulator") == [
        ("camera", "CCD Imager Simulator"),
        ("filter_wheel", "CCD Imager Simulator (wheel)"),
        ("focuser", "CCD Imager Simulator (focuser)"),
    ]


_real_sleep = asyncio.sleep


async def _no_sleep(_delay: float) -> None:
    await _real_sleep(0)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

async def test_drivers_endpoint_serves_the_indigo_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from httpx import ASGITransport, AsyncClient

    from astrolol.config.settings import settings
    from astrolol.main import create_app

    (tmp_path / "indigo_drivers").write_text(_DRIVER_LIST)
    monkeypatch.setattr(settings, "indi_server_kind", "indigo")
    monkeypatch.setattr(indigo, "catalog_dirs", lambda _path: [tmp_path])
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/indi/drivers/camera")
    assert r.status_code == 200
    assert {d["executable"] for d in r.json()} == {"indigo_ccd_asi", "indigo_ccd_simulator"}


async def test_server_endpoint_says_which_server(monkeypatch: pytest.MonkeyPatch) -> None:
    from httpx import ASGITransport, AsyncClient

    from astrolol.config.settings import settings
    from astrolol.main import create_app

    monkeypatch.setattr(settings, "indi_server_kind", "indigo")
    monkeypatch.setattr(settings, "indi_manage_server", False)
    monkeypatch.setattr(settings, "indi_host", "astro.local")
    monkeypatch.setattr(settings, "indi_port", 7625)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/indi/server")
    assert r.status_code == 200
    info = r.json()
    assert {k: info[k] for k in ("kind", "managed", "host", "port")} == {
        "kind": "indigo", "managed": False, "host": "astro.local", "port": 7625,
    }


def test_environment_selects_indigo(monkeypatch: pytest.MonkeyPatch) -> None:
    from astrolol.config.settings import Settings
    monkeypatch.setenv("ASTROLOL_INDI_SERVER_KIND", "indigo")
    monkeypatch.setenv("ASTROLOL_INDIGO_SERVER_PATH", "/opt/indigo/bin/indigo_server")
    s = Settings()
    assert (s.indi_server_kind, s.indigo_server_path) == ("indigo", "/opt/indigo/bin/indigo_server")
