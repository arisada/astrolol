"""
INDIGO servers: driver catalog, device interfaces and server lifecycle.

An INDIGO server speaks the INDI protocol to astrolol, so the INDI adapters and IndiClient
drive its devices. What differs is around them:

  - Drivers are loaded and unloaded through the server's own "Server" device (DRIVERS /
    LOAD / UNLOAD properties), not a FIFO, and only INDIGO drivers can be loaded at run time:
    an INDI driver (astrolol's own INDI mount proxy) runs as a process of its own, named on
    the command line (-i), so changing those means starting the server again.
  - The catalog is INDIGO's driver list: files of ``"name", "label", version`` lines in
    ``<prefix>/share/indigo`` (what indigo_server itself reads), or the server's DRIVERS
    property when only a remote server has it.
  - One driver attaches several devices ("CCD Imager Simulator", "… (wheel)", "… (guider)");
    each says which driver it belongs to (DRIVER_INFO.DEVICE_DRIVER) and what it is
    (DRIVER_INFO.DRIVER_INTERFACE, a bitmask).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from astrolol.devices.indi.allowed import DriverNotAllowed, check_driver, indi_catalog
from astrolol.devices.indi.catalog import DriverEntry
from astrolol.devices.indi.children import terminate

if TYPE_CHECKING:  # only for the annotation: the client is imported where it is used
    from astrolol.devices.indi.client import IndiClient

logger = structlog.get_logger()

SERVER_DEVICE = "Server"
_STATE_NAME = "astrolol_indigo.json"
_START_TIMEOUT = 10.0
_LOAD_TIMEOUT = 15.0
# indigo_server keeps a driver's path in INDIGO_NAME_SIZE (128) bytes and cuts longer ones.
MAX_INDI_DRIVER_PATH = 127

# DRIVER_INTERFACE bits (indigo_bus.h).
INTERFACE_MOUNT = 1 << 0
INTERFACE_CCD = 1 << 1
INTERFACE_GUIDER = 1 << 2
INTERFACE_FOCUSER = 1 << 3
INTERFACE_WHEEL = 1 << 4
INTERFACE_AO = 1 << 8
INTERFACE_ROTATOR = 1 << 12
INTERFACE_AUX = 1 << 15
INTERFACE_AUX_DUSTCAP = INTERFACE_AUX | (1 << 20)
INTERFACE_AUX_LIGHTBOX = INTERFACE_AUX | (1 << 21)

# Device kinds astrolol drives, and the interface bits that make a device one of them.
_KIND_INTERFACES: list[tuple[str, int]] = [
    ("camera", INTERFACE_CCD),
    ("mount", INTERFACE_MOUNT),
    ("focuser", INTERFACE_FOCUSER),
    ("filter_wheel", INTERFACE_WHEEL),
    ("rotator", INTERFACE_ROTATOR),
    ("flat_panel", INTERFACE_AUX_DUSTCAP),
    ("flat_panel", INTERFACE_AUX_LIGHTBOX),
]


def kinds_of_interface(interface: int) -> list[str]:
    """The device kinds a DRIVER_INTERFACE value names, in a stable order, without repeats."""
    kinds: list[str] = []
    for kind, bits in _KIND_INTERFACES:
        if interface & bits == bits and kind not in kinds:
            kinds.append(kind)
    return kinds


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

# Driver name prefix → device kind, as in the INDI catalog ("aux" = shown as a raw device).
_PREFIX_KINDS: dict[str, str] = {
    "ccd": "camera",
    "mount": "mount",
    "focuser": "focuser",
    "wheel": "filter_wheel",
    "rotator": "rotator",
}
# The INDI catalog's groups, so both catalogs read the same in the picker.
_KIND_GROUPS: dict[str, str] = {
    "camera": "CCDs",
    "mount": "Telescopes",
    "focuser": "Focusers",
    "filter_wheel": "Filter Wheels",
    "rotator": "Rotators",
    "flat_panel": "Auxiliary",
    "aux": "Auxiliary",
}
# indigo_aux_* drivers that are flat panels or dust covers.
# Properties every INDIGO device has that set up the server, not how the device connects:
# its saved profiles, extra copies of the device, a password. The connect wizard shows them
# greyed out and never sends them.
SERVER_ONLY_PROPERTIES: frozenset[str] = frozenset({
    "ADDITIONAL_INSTANCES",
    "AUTHENTICATION",
    "CONFIG_PROCESS",   # INDIGO's CONFIG, translated: saves the profile
    "PROFILE",
    "PROFILE_NAME",
})

FLAT_PANEL_DRIVERS: frozenset[str] = frozenset({
    "indigo_aux_alto", "indigo_aux_arteskyflat", "indigo_aux_flatmaster", "indigo_aux_flipflat",
    "indigo_aux_geoptikflat", "indigo_aux_giotto", "indigo_aux_wcv4ec",
})
# INDIGO's agents run astrolol-like automation inside the server; they are not devices.
_SKIPPED_PREFIXES = ("indigo_agent_",)

# The driver list only has a label; its manufacturer is the label's first word except for
# these, which take several words or name a protocol rather than a maker.
_MULTI_WORD_MAKERS = (
    "Alnitak Astrosystems", "Baader Planetarium", "Deep Sky Dad", "Interactive Astronomy",
    "Lunatico Astronomia", "Moravian Instruments", "Player One", "Rigel Systems",
    "Starlight Xpress",
)
_OTHER_MAKERS = frozenset({
    "indigo_ccd_libcamera", "indigo_ccd_ptp", "indigo_ccd_uvc", "indigo_aux_joystick",
    "indigo_aux_rpio", "indigo_aux_rts", "indigo_aux_usbdp", "indigo_gps_gpsd", "indigo_gps_nmea",
    "indigo_mount_lx200", "indigo_wheel_manual", "indigo_focuser_usbv3", "indigo_system_alpaca",
})


def kind_of_driver(name: str) -> str:
    if name in FLAT_PANEL_DRIVERS:
        return "flat_panel"
    prefix = name.removeprefix("indigo_").split("_", 1)[0]
    return _PREFIX_KINDS.get(prefix, "aux")


def _manufacturer(name: str, label: str) -> str:
    if name.endswith("_simulator"):
        return "Simulator"
    if name in _OTHER_MAKERS:
        return "Others"
    for maker in _MULTI_WORD_MAKERS:
        if label.startswith(maker):
            return maker
    return label.split(" ", 1)[0] or "Others"


def driver_entry(name: str, label: str) -> DriverEntry | None:
    """A catalog entry for INDIGO driver *name*, or None if it is not a device driver."""
    if not name.startswith("indigo_") or name.startswith(_SKIPPED_PREFIXES):
        return None
    kind = kind_of_driver(name)
    return DriverEntry(
        label=label or name,
        executable=name,
        # INDIGO device names are only known once the driver runs; the API finds a
        # driver's devices by DRIVER_INFO.DEVICE_DRIVER instead.
        device_name=label or name,
        group=_KIND_GROUPS[kind],
        kind=kind,
        manufacturer=_manufacturer(name, label),
    )


def _parse_driver_list(text: str) -> list[tuple[str, str]]:
    drivers: list[tuple[str, str]] = []
    for line in text.splitlines():
        fields = re.findall(r'"([^"]*)"', line)
        if len(fields) >= 2 and fields[0]:
            drivers.append((fields[0], fields[1]))
    return drivers


def catalog_dirs(server_path: str) -> list[Path]:
    """Where indigo_server looks for its driver list: next to the binary, then system-wide."""
    dirs: list[Path] = []
    found = shutil.which(server_path)
    if found:
        dirs.append(Path(os.path.realpath(found)).parent.parent / "share" / "indigo")
    dirs += [Path("/usr/share/indigo"), Path("/usr/local/share/indigo")]
    return dirs


def load_catalog(dirs: list[Path]) -> list[DriverEntry]:
    """Every device driver in the INDIGO driver lists found in *dirs*, each once."""
    entries: dict[str, DriverEntry] = {}
    for d in dirs:
        for name in ("indigo_drivers", "indigo_linux_drivers"):
            try:
                text = (d / name).read_text()
            except OSError:
                continue
            for driver, label in _parse_driver_list(text):
                entry = driver_entry(driver, label)
                if entry is not None and driver not in entries:
                    entries[driver] = entry
    return sorted(entries.values(), key=lambda e: (e.kind, e.manufacturer, e.label))


def catalog_from_server(client: IndiClient) -> list[DriverEntry]:
    """The catalog a running server publishes in its DRIVERS property (empty if none)."""
    v = client._get_vector(SERVER_DEVICE, "DRIVERS")
    if v is None:
        return []
    entries = [driver_entry(name, str(v.data[name].label or name)) for name in v.data]
    return sorted((e for e in entries if e is not None), key=lambda e: (e.kind, e.manufacturer, e.label))


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------

def _driver_info(client: IndiClient, device: str, member: str) -> str | None:
    v = client._get_vector(device, "DRIVER_INFO")
    if v is None or member not in v.data:
        return None
    return str(v[member])


def device_driver(client: IndiClient, device: str) -> str | None:
    return _driver_info(client, device, "DEVICE_DRIVER")


def device_interface(client: IndiClient, device: str) -> int:
    try:
        return int(_driver_info(client, device, "DRIVER_INTERFACE") or 0)
    except ValueError:
        return 0


def devices_of_driver(client: IndiClient, driver: str) -> list[str]:
    """The devices *driver* has attached, that astrolol can use as one of its device kinds.

    Guide outputs and adaptive optics attached on their own ("… (guider)", "… (AO)") are
    left out: the camera or mount they belong to uses them.
    """
    return [
        d for d in client.list_devices()
        if device_driver(client, d) == driver and kinds_of_interface(device_interface(client, d))
    ]


def devices_for_kind(client: IndiClient, devices: list[str], kind: str) -> list[str]:
    """Those of *devices* that are a *kind*, or all of them if none is.

    A camera driver also attaches its filter wheel and focuser ("… (wheel)"): they connect
    with the camera as its companions, and are no camera to pick.
    """
    matching = [d for d in devices if kind in kinds_of_interface(device_interface(client, d))]
    return matching or devices


def companion_devices(client: IndiClient, device: str) -> list[tuple[str, str]]:
    """(kind, device) for each device *device*'s driver attached as a part of it.

    INDIGO names those after the device: "CCD Imager Simulator (wheel)", "… (focuser)".
    """
    driver = device_driver(client, device)
    if driver is None:
        return []
    companions: list[tuple[str, str]] = []
    for d in client.list_devices():
        if d.startswith(device + " (") and device_driver(client, d) == driver:
            for kind in kinds_of_interface(device_interface(client, d)):
                companions.append((kind, d))
    return companions


# INDIGO's CCD simulator focuser starts in focus at position 0 (its range is ±20000) and blurs
# by one pixel every 15 steps, so 500 steps lose the stars. Set up like a real focuser: in focus
# at a positive position, with a curve a few thousand steps wide.
SIMULATOR_DRIVER = "indigo_ccd_simulator"
SIMULATOR_FOCUS_POSITION = 10000
SIMULATOR_BLUR_SCALE = 500      # steps per pixel of blur; the driver's default is 15
_SIMULATOR_DEFAULT_BLUR_SCALE = 15


async def setup_simulator_focuser(client: IndiClient, device: str) -> bool:
    """Set INDIGO's simulated focuser up like a real one, if it is still as the driver started it.

    Moves the point of focus to SIMULATOR_FOCUS_POSITION (a sync: the focuser reads that
    position without moving) and widens the focus curve. A focuser already moved, or whose
    blur was changed, is left alone, so reconnecting changes nothing. True if it changed it.
    """
    if device_driver(client, device) != SIMULATOR_DRIVER:
        return False
    try:
        await client.wait_for_property(device, "FOCUSER_SETUP", timeout=5.0)
        position = await client.get_number(device, "ABS_FOCUS_POSITION", "FOCUS_ABSOLUTE_POSITION")
        focus = await client.get_number(device, "FOCUSER_SETUP", "FOCUS")
        backlash = await client.get_number(device, "FOCUSER_SETUP", "BACKLASH")
        blur = await client.get_number(device, "FOCUSER_SETUP", "BLUR_SCALE")
        changed = False
        if position == 0 and focus == 0:
            await client.set_switch(device, "FOCUSER_ON_POSITION_SET", ["SYNC"])
            try:
                await client.set_number(device, "ABS_FOCUS_POSITION",
                                        {"FOCUS_ABSOLUTE_POSITION": SIMULATOR_FOCUS_POSITION})
                await client._wait_cond(
                    lambda: client.get_number_nowait(device, "ABS_FOCUS_POSITION", "FOCUS_ABSOLUTE_POSITION")
                    == SIMULATOR_FOCUS_POSITION,
                    timeout=5.0,
                )
            finally:
                await client.set_switch(device, "FOCUSER_ON_POSITION_SET", ["GOTO"])
            changed = True
        if blur == _SIMULATOR_DEFAULT_BLUR_SCALE:
            await client.set_number(device, "FOCUSER_SETUP",
                                    {"FOCUS": focus, "BACKLASH": backlash, "BLUR_SCALE": SIMULATOR_BLUR_SCALE})
            changed = True
    except Exception as exc:  # a simulator nicety: never fail the connection over it
        logger.warning("indigo.simulator_focuser_setup_failed", device=device, error=str(exc))
        return False
    if changed:
        logger.info("indigo.simulator_focuser_set_up", device=device,
                    focus_position=SIMULATOR_FOCUS_POSITION, blur_scale=SIMULATOR_BLUR_SCALE)
    return changed


def indi_driver_device(device: str, executable: str) -> str:
    """The name an INDIGO server gives *device* of INDI driver *executable* run with -i."""
    return f"{device} @ {Path(executable).name}"


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------

class IndigoServer:
    """
    Lifecycle of an indigo_server, with the interface of IndiServer.

    Managed: astrolol starts indigo_server (detached, so it survives astrolol restarts; the
    PID is kept in <run_dir>/astrolol_indigo.json for the next instance). Unmanaged: astrolol
    connects to one already running. Either way drivers are loaded through the server's
    "Server" device, which needs the client connected: start() comes first, then the client
    connects, then load_driver().
    """

    def __init__(
        self,
        client: IndiClient,
        manage: bool = True,
        host: str = "localhost",
        port: int = 7624,
        run_dir: Path = Path("/tmp/astrolol"),
        server_path: str = "indigo_server",
    ) -> None:
        self._client = client
        self.manage = manage
        self.host = host
        self.port = port
        self._run_dir = run_dir
        self._state_path = run_dir / _STATE_NAME
        self._server_path = server_path
        self._managed_pid: int | None = None
        self._process: asyncio.subprocess.Process | None = None   # when this run started it
        # INDI drivers to run alongside, set before start(); those the running server has.
        self.indi_drivers: list[str] = []
        self._loaded_drivers: set[str] = set()

    async def start(self) -> None:
        if not self.manage:
            logger.info("indigo.server_unmanaged", host=self.host, port=self.port)
            return
        if self._managed_pid is not None:
            return
        state = self._read_state()
        pid = (state or {}).get("pid")
        if pid and self._is_indigo_server(pid):
            running = sorted((state or {}).get("indi_drivers", []))
            same_port = (state or {}).get("port", self.port) == self.port
            if running == sorted(self.indi_drivers) and same_port:
                logger.info("indigo.server_reusing", pid=pid)
                self._managed_pid = pid
                self._loaded_drivers = set(running)
                return
            # Started with other INDI drivers, which it cannot change while it runs, or on
            # another port (changed in Options since).
            logger.info("indigo.server_restarting", pid=pid, running=running, wanted=self.indi_drivers,
                        old_port=(state or {}).get("port"), port=self.port)
            await self.stop()
            for _ in range(50):     # its worker lets go of the port a moment later
                if not _port_in_use(self.port):
                    break
                await asyncio.sleep(0.1)
        elif state:
            logger.info("indigo.server_stale_state", old_pid=pid)
            self._cleanup_state()

        if _port_in_use(self.port):
            raise RuntimeError(
                f"Port {self.port} is in use by an unknown process. "
                "Stop it before starting astrolol, or switch to unmanaged mode."
            )
        found = shutil.which(self._server_path)
        if found is None:
            raise RuntimeError(f"{self._server_path} not found; is INDIGO installed?")
        # By its real path: indigo_server finds its driver list next to the binary
        # (<prefix>/bin/../share/indigo), which a symlink on PATH would hide.
        cmd = [
            os.path.realpath(found),
            "-p", str(self.port),
            # No network announcement, and none of INDIGO's web pages: they would let
            # anyone on the network drive the devices without going through astrolol.
            "-b-", "-w-", "-c-",
        ]
        indi_drivers = [d for d in self.indi_drivers if self._fits(d) and self._allowed_indi(d)]
        for driver in indi_drivers:
            cmd += ["-i", driver]
        logger.info("indigo.server_starting", cmd=" ".join(cmd))
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = asyncio.get_running_loop().time() + _START_TIMEOUT
        while not _port_in_use(self.port):
            if process.returncode is not None:
                raise RuntimeError(f"indigo_server exited immediately (rc={process.returncode})")
            if asyncio.get_running_loop().time() > deadline:
                process.kill()
                await process.wait()
                raise RuntimeError(f"indigo_server did not open port {self.port}")
            await asyncio.sleep(0.2)
        self._managed_pid = process.pid
        self._process = process
        self._loaded_drivers = set(indi_drivers)
        self._save_state()
        logger.info("indigo.server_started", pid=process.pid, port=self.port)

    async def stop(self) -> None:
        """Stop a managed indigo_server (its worker process goes with it)."""
        if not self.manage:
            return
        pid = (self._read_state() or {}).get("pid") or self._managed_pid
        if pid is None:
            logger.info("indigo.server_not_running")
            return
        logger.info("indigo.server_stopping", pid=pid)
        await terminate(pid, self._process)
        self._managed_pid = None
        self._process = None
        self._loaded_drivers = set()
        self._cleanup_state()
        logger.info("indigo.server_stopped", pid=pid)

    async def stop_left_over(self) -> None:
        """Stop the INDIGO server a previous run left running (astrolol now uses another server)."""
        if not self.manage:
            return
        pid = (self._read_state() or {}).get("pid")
        if pid and self._is_indigo_server(pid):
            await self.stop()
        else:
            self._cleanup_state()

    def runs(self, executable: str) -> bool:
        """Whether the running server has *executable*, an INDI driver, from its start."""
        return executable in self._loaded_drivers

    async def load_driver(self, executable: str) -> None:
        """Load an INDIGO driver (a no-op if it is loaded already).

        An INDI driver can only have been given at start (indi_drivers): loading one is a
        no-op if the server has it, and an error otherwise.
        """
        if not executable.startswith("indigo_"):
            if self.runs(executable):
                return
            raise ValueError(
                f"{executable} is not an INDIGO driver; an INDIGO server cannot load "
                "other drivers while it runs."
            )
        await self._client.wait_for_property(SERVER_DEVICE, "LOAD", timeout=_LOAD_TIMEOUT)
        check_driver(executable, self._run_dir, self._indigo_catalog)
        if self._is_loaded(executable):
            logger.debug("indigo.driver_already_loaded", driver=executable)
            return
        await self._client.set_text(SERVER_DEVICE, "LOAD", {"DRIVER": executable})
        try:
            await self._client._wait_cond(
                lambda: self._is_loaded(executable)
                or self._client._vector_state(SERVER_DEVICE, "LOAD") == "Alert",
                timeout=_LOAD_TIMEOUT,
            )
        except TimeoutError:
            # A driver missing from the DRIVERS list loads without it ever saying so.
            if self._client._get_vector(SERVER_DEVICE, "DRIVERS") is not None:
                raise
        if self._client._vector_state(SERVER_DEVICE, "LOAD") == "Alert":
            raise RuntimeError(f"INDIGO could not load {executable}")
        logger.info("indigo.driver_loaded", driver=executable)

    async def unload_driver(self, executable: str) -> None:
        if not executable.startswith("indigo_"):
            return
        if self._client._get_vector(SERVER_DEVICE, "UNLOAD") is None:
            return
        await self._client.set_text(SERVER_DEVICE, "UNLOAD", {"DRIVER": executable})
        logger.info("indigo.driver_unloaded", driver=executable)

    @property
    def is_running(self) -> bool:
        if not self.manage:
            return True
        pid = self._managed_pid or (self._read_state() or {}).get("pid")
        return bool(pid and self._is_indigo_server(pid))

    def _indigo_catalog(self) -> list[str]:
        """The INDIGO drivers on this machine, and those the server says it has."""
        entries = load_catalog(catalog_dirs(self._server_path)) + catalog_from_server(self._client)
        return [e.executable for e in entries]

    def _allowed_indi(self, driver: str) -> bool:
        try:
            check_driver(driver, self._run_dir, indi_catalog)
        except DriverNotAllowed as exc:
            logger.error("indigo.indi_driver_refused", driver=driver, error=str(exc))
            return False
        return True

    @staticmethod
    def _fits(driver: str) -> bool:
        if len(driver.encode()) <= MAX_INDI_DRIVER_PATH:
            return True
        logger.error(
            "indigo.indi_driver_path_too_long", driver=driver, max_length=MAX_INDI_DRIVER_PATH,
        )
        return False

    def _is_loaded(self, executable: str) -> bool:
        if self._client.get_switch_state_nowait(SERVER_DEVICE, "DRIVERS", executable):
            return True
        # Drivers that are not in the server's list still announce their devices.
        return any(device_driver(self._client, d) == executable for d in self._client.list_devices())

    @staticmethod
    def _is_indigo_server(pid: int) -> bool:
        try:
            return Path(f"/proc/{pid}/comm").read_text().strip() == "indigo_server"
        except OSError:
            return False

    def _read_state(self) -> dict | None:
        try:
            return json.loads(self._state_path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def _save_state(self) -> None:
        try:
            self._run_dir.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps({
                "pid": self._managed_pid,
                "port": self.port,
                "indi_drivers": sorted(self._loaded_drivers),
            }))
        except OSError as exc:
            logger.warning("indigo.state_save_failed", error=str(exc))

    def _cleanup_state(self) -> None:
        try:
            self._state_path.unlink(missing_ok=True)
        except OSError:
            pass


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0
