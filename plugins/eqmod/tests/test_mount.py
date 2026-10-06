"""Tests for the real eqmod adapter against a fake controller speaking the wire protocol."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import astropy.units as u
import pytest
from astropy.coordinates import SkyCoord

from astrolol.devices.base.models import TrackingMode
from plugins.eqmod import mount as mount_module
from astrolol.mount.sky import icrs_to_jnow, jnow_to_icrs, local_sidereal_time_h
from plugins.eqmod.geometry import MountGeometry, PierSide
from plugins.eqmod.mount import EqmodMount, EqmodNotReadyError
from plugins.eqmod.protocol import (
    SIDEREAL_DEG_PER_SEC,
    decode_uint,
    encode_position,
    encode_uint,
    step_period_for_rate,
)

CPR = 4_608_000
TIMER_FREQ = 16_000_000
HS_RATIO = 16
NOW = datetime(2026, 9, 24, 22, 0, tzinfo=timezone.utc)
SITE = (48.85, 2.35, 35.0)


@dataclass
class _AxisState:
    running: bool = False
    tracking_mode: bool = True
    fast: bool = False
    ccw: bool = False
    period: int = 0
    position: int = 0
    increment: int = 0
    polls_until_stopped: int = 0


@dataclass
class _FakeController:
    """Speaks the Sky-Watcher wire protocol. GOTOs land after `goto_lag_polls` status polls;
    a :K stop takes `stop_lag_polls` polls. Speed-mode motion does not change position."""

    axes: dict[int, _AxisState] = field(default_factory=lambda: {1: _AxisState(), 2: _AxisState()})
    log: list[str] = field(default_factory=list)
    initialized: bool = False
    stop_lag_polls: int = 0
    goto_lag_polls: int = 1
    opened: bool = False
    closed: bool = False

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True

    async def request(self, command: bytes) -> bytes:
        text = command.decode().rstrip("\r")
        cmd, ch, data = text[1], int(text[2]), text[3:]
        targets = [1, 2] if ch == 3 else [ch]
        ax = self.axes.get(targets[0])
        if cmd in "GHIJKL":
            self.log.append(text)
        if cmd == "e":
            return b"=031205\r"
        if cmd == "b":
            return f"={encode_uint(TIMER_FREQ, 24)}\r".encode()
        if cmd == "a":
            return f"={encode_uint(CPR, 24)}\r".encode()
        if cmd == "g":
            return f"={encode_uint(HS_RATIO, 8)}\r".encode()
        if cmd == "F":
            self.initialized = True
            return b"=\r"
        if cmd == "f":
            if ax.polls_until_stopped:
                ax.polls_until_stopped -= 1
                if not ax.polls_until_stopped:
                    ax.running = False
            n0 = (1 if ax.tracking_mode else 0) | (2 if ax.ccw else 0) | (4 if ax.fast else 0)
            return f"={n0:X}{1 if ax.running else 0:X}{1 if self.initialized else 0:X}\r".encode()
        if cmd == "G":
            if ax.running:
                return b"!2\r"
            db1, db2 = int(data[0], 16), int(data[1], 16)
            ax.tracking_mode = bool(db1 & 1)
            ax.fast = bool(db1 & 2) if ax.tracking_mode else not (db1 & 2)
            ax.ccw = bool(db2 & 1)
            return b"=\r"
        if cmd == "H":
            ax.increment = decode_uint(data)
            return b"=\r"
        if cmd == "I":
            ax.period = decode_uint(data)
            return b"=\r"
        if cmd == "J":
            ax.running = True
            if not ax.tracking_mode:
                ax.position += -ax.increment if ax.ccw else ax.increment
                ax.polls_until_stopped = self.goto_lag_polls
            return b"=\r"
        if cmd == "K":
            for t in targets:
                a = self.axes[t]
                if a.running and self.stop_lag_polls:
                    a.polls_until_stopped = self.stop_lag_polls
                else:
                    a.running = False
            return b"=\r"
        if cmd == "L":
            for t in targets:
                self.axes[t].running = False
                self.axes[t].polls_until_stopped = 0
            return b"=\r"
        if cmd == "j":
            return f"={encode_position(ax.position)}\r".encode()
        if cmd == "i":
            return f"={encode_uint(ax.period, 24)}\r".encode()
        if cmd == "q":
            return b"=000000\r"
        if cmd == "V":
            return b"=\r"
        return b"!0\r"


async def _idle_pump(self) -> None:
    import asyncio
    await asyncio.Event().wait()


@pytest.fixture(autouse=True)
def _fast_and_deterministic(monkeypatch, tmp_path):
    # A real pump outliving the test could persist into the user's real data dir after teardown.
    monkeypatch.setattr(EqmodMount, "_coords_pump", _idle_pump)
    monkeypatch.setattr(mount_module, "AXIS_STOP_POLL_INTERVAL", 0)
    monkeypatch.setattr(mount_module, "GOTO_POLL_INTERVAL", 0)
    monkeypatch.setattr(mount_module, "_now", lambda: NOW)
    monkeypatch.setenv("ASTROLOL_DATA_DIR", str(tmp_path))


async def _connected(controller: _FakeController | None = None, located: bool = True, **params):
    ctrl = controller or _FakeController()
    mount = EqmodMount(port="/dev/fake", baudrate=9600, transport_factory=lambda port, baud: ctrl, **params)
    await mount.connect()
    if located:
        await mount.set_location(*SITE)
    ctrl.log.clear()
    return mount, ctrl


def _lst() -> float:
    return local_sidereal_time_h(NOW, SITE[1])


def _expected_counts(coord: SkyCoord, **geo_kwargs) -> tuple[int, int, PierSide]:
    ra_jnow, dec = icrs_to_jnow(coord, NOW)
    return MountGeometry(CPR, CPR, **geo_kwargs).target_counts(ra_jnow, dec, _lst())


def _star(ha_h: float, dec_deg: float) -> SkyCoord:
    """ICRS coordinate that sits at the given HA (equinox of date) at NOW."""
    return jnow_to_icrs((_lst() - ha_h) % 24.0, dec_deg, NOW)


# --- Connect / handshake ---

async def test_connect_requires_port() -> None:
    with pytest.raises(ValueError, match="port"):
        await EqmodMount().connect()


async def test_connect_runs_handshake_and_initializes() -> None:
    mount, ctrl = await _connected()
    assert ctrl.opened and ctrl.initialized
    diag = await mount.diagnostics()
    assert diag["board_version"] == "051203"
    assert diag["timer_freq"] == TIMER_FREQ
    assert diag["axes"]["RA"]["cpr"] == CPR
    assert diag["axes"]["DEC"]["high_speed_ratio"] == HS_RATIO


async def test_connect_requires_port_or_bluetooth_device_id() -> None:
    with pytest.raises(ValueError, match="bluetooth_device_id"):
        await EqmodMount().connect()


async def test_connect_over_bluetooth_skips_baudrate_detection() -> None:
    ctrl = _FakeController()
    opened_with: list[tuple[object, str]] = []

    def factory(manager, device_id):
        opened_with.append((manager, device_id))
        return ctrl

    fake_manager = object()
    mount = EqmodMount(
        bluetooth_device_id="AA:BB:CC:DD:EE:FF",
        bluetooth_manager=fake_manager,
        bluetooth_transport_factory=factory,
    )
    await mount.connect()
    assert ctrl.opened and ctrl.initialized
    assert opened_with == [(fake_manager, "AA:BB:CC:DD:EE:FF")]
    diag = await mount.diagnostics()
    assert diag["bluetooth_device_id"] == "AA:BB:CC:DD:EE:FF"
    assert diag["baudrate"] is None


async def test_connect_over_bluetooth_without_manager_raises() -> None:
    with pytest.raises(ValueError, match="BluetoothManager"):
        await EqmodMount(bluetooth_device_id="AA:BB:CC:DD:EE:FF").connect()


async def test_connect_failure_closes_transport() -> None:
    class _Broken(_FakeController):
        async def request(self, command: bytes) -> bytes:
            return b"!0\r"

    ctrl = _Broken()
    with pytest.raises(Exception):
        await EqmodMount(port="/dev/fake", baudrate=9600, transport_factory=lambda p, b: ctrl).connect()
    assert ctrl.closed


async def test_connect_picks_up_tracking_already_running() -> None:
    ctrl = _FakeController()
    ctrl.axes[1].running = True
    mount, _ = await _connected(ctrl)
    assert (await mount.get_status()).is_tracking is True


async def test_fresh_mount_at_home_reports_parked_at_the_pole() -> None:
    mount, _ = await _connected()
    s = await mount.get_status()
    assert s.is_parked is True
    assert s.is_synced is False
    assert s.dec == pytest.approx(90.0, abs=0.5)  # ICRS vs of-date pole differ by precession
    assert s.pier_side == "East"
    assert s.lst == pytest.approx(_lst())


async def test_status_without_location_has_no_sky_coordinates() -> None:
    mount, _ = await _connected(located=False)
    s = await mount.get_status()
    assert s.ra is None and s.dec is None and s.alt is None
    assert s.pier_side == "East"


# --- Nudge ---

@pytest.mark.parametrize("direction,axis,ccw", [
    ("W", 1, False), ("E", 1, True),
    # At home the OTA is on the east side, where north means turning the Dec axis negative.
    ("N", 2, True), ("S", 2, False),
])
async def test_nudge_at_home(direction: str, axis: int, ccw: bool) -> None:
    mount, ctrl = await _connected()
    await mount.start_move(direction, "centering")
    a = ctrl.axes[axis]
    assert a.running and a.tracking_mode and a.ccw is ccw and not a.fast
    assert a.period == step_period_for_rate(16 * SIDEREAL_DEG_PER_SEC, CPR, TIMER_FREQ)
    assert not ctrl.axes[3 - axis].running


async def test_north_swaps_direction_on_the_west_pier_side() -> None:
    ctrl = _FakeController()
    ctrl.axes[2].position = -CPR // 8  # Dec axis at -45 deg: OTA west of the pier
    mount, _ = await _connected(ctrl)
    await mount.start_move("N", "centering")
    assert ctrl.axes[2].ccw is False


async def test_reverse_flag_flips_direction() -> None:
    mount, ctrl = await _connected(dec_reverse=True)
    await mount.start_move("N", "centering")
    assert ctrl.axes[2].ccw is False


async def test_max_rate_uses_high_speed_mode() -> None:
    mount, ctrl = await _connected()
    await mount.start_move("W", "max")
    a = ctrl.axes[1]
    assert a.fast
    assert a.period == step_period_for_rate(400 * SIDEREAL_DEG_PER_SEC, CPR, TIMER_FREQ, HS_RATIO)


async def test_nudge_unparks() -> None:
    mount, _ = await _connected()
    await mount.start_move("W", "guide")
    assert (await mount.get_status()).is_parked is False


async def test_stop_move_stops_axis_and_waits_for_it() -> None:
    mount, ctrl = await _connected(_FakeController(stop_lag_polls=3))
    await mount.start_move("N", "find")
    await mount.stop_move()
    assert not ctrl.axes[2].running
    assert (await mount.get_status()).is_slewing is False


async def test_stop_move_resumes_tracking_after_ra_nudge() -> None:
    mount, ctrl = await _connected()
    await mount.set_tracking(True, TrackingMode.SIDEREAL)
    await mount.start_move("E", "centering")
    await mount.stop_move()
    ra = ctrl.axes[1]
    assert ra.running and ra.ccw is False
    assert ra.period == step_period_for_rate(SIDEREAL_DEG_PER_SEC, CPR, TIMER_FREQ)


# --- Tracking ---

@pytest.mark.parametrize("mode", list(TrackingMode))
async def test_tracking_rates(mode: TrackingMode) -> None:
    mount, ctrl = await _connected()
    await mount.set_tracking(True, mode)
    ra = ctrl.axes[1]
    expected = step_period_for_rate(mount_module.TRACKING_RATES_DEG_PER_SEC[mode], CPR, TIMER_FREQ)
    assert ra.running and ra.period == expected and ra.ccw is False
    assert (await mount.get_status()).is_tracking


async def test_tracking_off_stops_ra() -> None:
    mount, ctrl = await _connected()
    await mount.set_tracking(True)
    await mount.set_tracking(False)
    assert not ctrl.axes[1].running
    assert (await mount.get_status()).is_tracking is False


# --- GOTO ---

@pytest.mark.parametrize("ha,dec,side", [(-2.0, 30.0, PierSide.WEST), (1.5, -10.0, PierSide.EAST)])
async def test_slew_goes_to_the_computed_counts_then_tracks(ha: float, dec: float, side: PierSide) -> None:
    mount, ctrl = await _connected()
    star = _star(ha, dec)
    await mount.slew(star)
    ra_c, dec_c, expected_side = _expected_counts(star)
    assert expected_side is side
    assert abs(ctrl.axes[1].position - ra_c) <= 1 and abs(ctrl.axes[2].position - dec_c) <= 1
    status = await mount.get_status()
    assert status.pier_side == side.value
    assert status.is_tracking and not status.is_parked and not status.is_slewing
    assert SkyCoord(ra=status.ra * u.hourangle, dec=status.dec * u.deg).separation(star).arcsec < 5
    assert ctrl.axes[1].running and ctrl.axes[1].tracking_mode  # tracking restarted


async def test_slew_uses_goto_mode_with_direction_from_delta() -> None:
    mount, ctrl = await _connected()
    await mount.slew(_star(-2.0, 30.0))  # west side: Dec axis goes negative from home
    goto_modes = [cmd for cmd in ctrl.log if cmd.startswith(":G2")]
    assert goto_modes[0] == ":G201"  # GOTO, fast, CCW


async def test_slew_without_location_fails_before_moving() -> None:
    mount, ctrl = await _connected(located=False)
    with pytest.raises(EqmodNotReadyError):
        await mount.slew(_star(-2.0, 30.0))
    assert not any(cmd.startswith(":J") for cmd in ctrl.log)


async def test_second_goto_pass_is_skipped_when_already_there() -> None:
    mount, ctrl = await _connected()
    await mount.slew(_star(-2.0, 30.0))
    starts = [cmd for cmd in ctrl.log if cmd.startswith(":J")]
    assert len(starts) == 3  # RA + Dec GOTO, then the tracking start; pass 2 had nothing to do


async def test_cancelled_slew_stops_both_axes() -> None:
    import asyncio

    mount, ctrl = await _connected(_FakeController(goto_lag_polls=10_000))
    task = asyncio.create_task(mount.slew(_star(-2.0, 30.0)))
    await asyncio.sleep(0)
    for _ in range(50):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ":L1" in ctrl.log and ":L2" in ctrl.log and ":L3" not in ctrl.log
    assert (await mount.get_status()).is_slewing is False


async def test_meridian_flip_keeps_the_target_on_the_other_side() -> None:
    mount, ctrl = await _connected()
    star = _star(0.2, 20.0)
    await mount.slew(star)
    assert (await mount.get_status()).pier_side == "East"
    await mount.meridian_flip()
    status = await mount.get_status()
    assert status.pier_side == "West"
    assert SkyCoord(ra=status.ra * u.hourangle, dec=status.dec * u.deg).separation(star).arcsec < 5


# --- Sync ---

async def test_sync_makes_the_reported_position_match_the_solve() -> None:
    mount, _ = await _connected()
    await mount.slew(_star(-2.0, 30.0))
    solved = _star(-1.9, 31.2)
    await mount.sync(solved)
    status = await mount.get_status()
    assert status.is_synced
    assert SkyCoord(ra=status.ra * u.hourangle, dec=status.dec * u.deg).separation(solved).arcsec < 5


async def test_sync_does_not_touch_the_controller_counters() -> None:
    mount, ctrl = await _connected()
    await mount.slew(_star(-2.0, 30.0))
    before = (ctrl.axes[1].position, ctrl.axes[2].position)
    ctrl.log.clear()
    await mount.sync(_star(-1.9, 31.2))
    assert (ctrl.axes[1].position, ctrl.axes[2].position) == before
    assert not any(cmd.startswith(":E") for cmd in ctrl.log)


async def test_slew_after_sync_uses_the_offset() -> None:
    mount, ctrl = await _connected()
    await mount.slew(_star(-2.0, 30.0))
    await mount.sync(_star(-1.9, 31.2))  # model was off by 0.1h / 1.2 deg
    target = _star(-3.0, 20.0)
    await mount.slew(target)
    status = await mount.get_status()
    assert SkyCoord(ra=status.ra * u.hourangle, dec=status.dec * u.deg).separation(target).arcsec < 5
    unsynced_ra, unsynced_dec, _ = _expected_counts(target)
    assert (ctrl.axes[1].position, ctrl.axes[2].position) != (unsynced_ra, unsynced_dec)


# --- Park ---

async def test_park_returns_to_home_and_stops_tracking() -> None:
    mount, ctrl = await _connected()
    await mount.slew(_star(-2.0, 30.0))
    await mount.park()
    assert (ctrl.axes[1].position, ctrl.axes[2].position) == (0, 0)
    status = await mount.get_status()
    assert status.is_parked and not status.is_tracking
    assert not ctrl.axes[1].running


async def test_custom_park_position_and_unpark() -> None:
    mount, ctrl = await _connected()
    await mount.slew(_star(-2.0, 30.0))
    park_here = (ctrl.axes[1].position, ctrl.axes[2].position)
    await mount.set_park_position()
    await mount.slew(_star(1.0, 10.0))
    await mount.park()
    assert (ctrl.axes[1].position, ctrl.axes[2].position) == park_here
    await mount.unpark()
    assert (await mount.get_status()).is_parked is False


# --- Persistence across an astrolol restart ---

async def test_sync_and_park_position_survive_a_restart() -> None:
    ctrl = _FakeController()
    mount, _ = await _connected(ctrl)
    await mount.slew(_star(-2.0, 30.0))
    await mount.set_park_position()
    await mount.sync(_star(-1.9, 31.2))
    await mount.set_tracking(False)
    await mount.disconnect()

    again, _ = await _connected(ctrl)
    diag = await again.diagnostics()
    assert diag["sync_offset"] is not None
    assert diag["park_counts"] == [ctrl.axes[1].position, ctrl.axes[2].position]
    assert (await again.get_status()).is_synced


async def test_power_cycle_discards_the_sync_but_keeps_the_park_position(tmp_path) -> None:
    ctrl = _FakeController()
    mount, _ = await _connected(ctrl)
    await mount.slew(_star(-2.0, 30.0))
    await mount.set_park_position()
    park = [ctrl.axes[1].position, ctrl.axes[2].position]
    await mount.sync(_star(-1.9, 31.2))
    await mount.disconnect()

    power_cycled = _FakeController()  # counters back at 0: home
    again, _ = await _connected(power_cycled)
    diag = await again.diagnostics()
    assert diag["sync_offset"] is None
    assert diag["park_counts"] == park
    assert (await again.get_status()).is_parked is True  # back at home


async def test_restart_while_tracking_accounts_for_elapsed_time(monkeypatch) -> None:
    ctrl = _FakeController()
    mount, _ = await _connected(ctrl)
    await mount.slew(_star(-2.0, 30.0))  # ends tracking
    await mount.sync(_star(-1.9, 31.2))
    await mount.disconnect()

    # Ten minutes later the RA counter has advanced by ten minutes of sidereal tracking.
    later = NOW + timedelta(minutes=10)
    monkeypatch.setattr(mount_module, "_now", lambda: later)
    ctrl.axes[1].position += round(SIDEREAL_DEG_PER_SEC * 600 * CPR / 360.0)
    again, _ = await _connected(ctrl)
    assert (await again.diagnostics())["sync_offset"] is not None


async def test_state_file_location(tmp_path) -> None:
    mount, _ = await _connected()
    await mount.park()
    data = json.loads((tmp_path / "eqmod" / "fake.json").read_text())
    assert data["is_parked"] is True and data["park_counts"] == [0, 0]


# --- Stop / disconnect / misc ---

async def test_stop_is_an_instant_stop_on_both_axes() -> None:
    mount, ctrl = await _connected()
    await mount.set_tracking(True)
    await mount.start_move("N", "centering")
    await mount.stop()
    assert ":L1" in ctrl.log and ":L2" in ctrl.log and ":L3" not in ctrl.log
    assert not ctrl.axes[1].running and not ctrl.axes[2].running
    assert (await mount.get_status()).is_tracking is False


async def test_disconnect_stops_nudge_but_keeps_tracking() -> None:
    mount, ctrl = await _connected()
    await mount.set_tracking(True)
    await mount.start_move("N", "centering")
    await mount.disconnect()
    assert ctrl.axes[1].running
    assert not ctrl.axes[2].running
    assert ctrl.closed


async def test_coords_listener_receives_the_pointing() -> None:
    import asyncio

    mount, _ = await _connected()
    calls: list[tuple] = []
    mount.set_coords_listener(lambda *args: calls.append(args))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    ra, dec, ra_jnow, dec_jnow, alt, az, pier, ha, lst, tracking, parked = calls[-1]
    assert dec == pytest.approx(90.0, abs=0.5) and pier == "East" and parked is True
    assert alt == pytest.approx(SITE[0], abs=0.5)  # the pole sits at altitude = latitude
    await mount.disconnect()


async def test_led_brightness_scales_percent_to_byte() -> None:
    mount, ctrl = await _connected()
    sent: list[bytes] = []
    original = ctrl.request

    async def spy(command: bytes) -> bytes:
        sent.append(command)
        return await original(command)

    ctrl.request = spy  # type: ignore[method-assign]
    await mount.set_led_brightness(100)
    assert sent == [b":V1FF\r"]


async def test_location_is_stored_and_reported() -> None:
    mount, _ = await _connected(located=False)
    assert (await mount.diagnostics())["location"] is None
    await mount.set_time_utc()
    await mount.set_location(*SITE)
    assert (await mount.diagnostics())["location"] == list(SITE)


async def test_ping() -> None:
    mount, _ = await _connected()
    assert await mount.ping() is True
    await mount.disconnect()
    assert await mount.ping() is False


class _NoBothChannelController(_FakeController):
    """Firmware that rejects channel "3" for stop commands (indi-eqmod never relies on it)."""

    async def request(self, command: bytes) -> bytes:
        if command[1:2] in (b"K", b"L") and command[2:3] == b"3":
            self.log.append(command.decode().rstrip("\r"))
            return b"!3\r"
        return await super().request(command)


async def test_stop_button_halts_a_goto_even_if_channel_3_is_rejected() -> None:
    """Regression: the Mount page Stop (MountManager.stop) did not stop a GOTO on real hardware."""
    import asyncio

    from astrolol.core.events import EventBus
    from astrolol.devices.config import DeviceConfig
    from astrolol.devices.manager import DeviceManager
    from astrolol.devices.registry import DeviceRegistry
    from astrolol.mount.manager import MountManager

    ctrl = _NoBothChannelController(goto_lag_polls=10**9)
    registry = DeviceRegistry()
    registry.register_mount("eq", lambda **p: EqmodMount(transport_factory=lambda a, b: ctrl, **p))
    bus = EventBus()
    devices = DeviceManager(registry=registry, event_bus=bus)
    manager = MountManager(device_manager=devices, event_bus=bus)
    await devices.connect(DeviceConfig(device_id="m", kind="mount", adapter_key="eq",
                                       params={"port": "/dev/fake", "baudrate": 9600}))
    await devices.get_mount("m").set_location(*SITE)
    await manager.set_target("m", _star(-2.0, 30.0))
    await manager.slew("m")
    for _ in range(20):
        await asyncio.sleep(0)
    assert ctrl.axes[1].running and ctrl.axes[2].running

    await manager.stop("m")

    assert not ctrl.axes[1].running and not ctrl.axes[2].running
    status = await devices.get_mount("m").get_status()
    assert not status.is_slewing and not status.is_tracking
    await devices.disconnect("m")


# --- Pulse guiding ---

def _period(deg_per_sec: float) -> int:
    return step_period_for_rate(deg_per_sec, CPR, TIMER_FREQ)


async def _mid_pulse(mount: EqmodMount, direction: str, ms: int = 80):
    """Start a pulse, return (task) after it has applied its speed change."""
    import asyncio
    task = asyncio.create_task(mount.pulse_guide(direction, ms))
    await asyncio.sleep(0.02)
    return task


@pytest.mark.parametrize("direction,factor", [("W", 1.5), ("E", 0.5)])
async def test_ra_pulse_while_tracking_shifts_speed_without_stopping(direction: str, factor: float) -> None:
    mount, ctrl = await _connected()
    await mount.unpark()
    await mount.set_tracking(True)
    ctrl.log.clear()
    task = await _mid_pulse(mount, direction)
    assert ctrl.axes[1].running
    assert ctrl.axes[1].period == _period(factor * SIDEREAL_DEG_PER_SEC)
    await task
    assert ctrl.axes[1].running and ctrl.axes[1].ccw is False
    assert ctrl.axes[1].period == _period(SIDEREAL_DEG_PER_SEC)
    assert not any(cmd.startswith((":K1", ":L1", ":G1")) for cmd in ctrl.log)  # never stopped


async def test_east_pulse_at_full_guide_rate_pauses_then_resumes_tracking() -> None:
    mount, ctrl = await _connected(guide_rate=1.0)
    await mount.unpark()
    await mount.set_tracking(True)
    task = await _mid_pulse(mount, "E")
    assert not ctrl.axes[1].running
    await task
    assert ctrl.axes[1].running and ctrl.axes[1].period == _period(SIDEREAL_DEG_PER_SEC)


@pytest.mark.parametrize("dec_counts,direction,ccw", [
    (0, "N", True), (0, "S", False),                 # east pier side
    (-CPR // 8, "N", False), (-CPR // 8, "S", True),  # west pier side: N/S swap
])
async def test_dec_pulse_runs_at_guide_rate_then_stops(dec_counts: int, direction: str, ccw: bool) -> None:
    ctrl = _FakeController()
    ctrl.axes[2].position = dec_counts
    mount, _ = await _connected(ctrl)
    await mount.unpark()
    task = await _mid_pulse(mount, direction)
    dec = ctrl.axes[2]
    assert dec.running and dec.ccw is ccw and dec.period == _period(0.5 * SIDEREAL_DEG_PER_SEC)
    await task
    assert not ctrl.axes[2].running


async def test_ra_pulse_without_tracking_runs_the_axis_briefly() -> None:
    mount, ctrl = await _connected()
    await mount.unpark()
    task = await _mid_pulse(mount, "W")
    assert ctrl.axes[1].running and ctrl.axes[1].ccw is False
    await task
    assert not ctrl.axes[1].running


async def test_pulse_lasts_its_duration() -> None:
    import time as _time
    mount, _ = await _connected()
    await mount.unpark()
    await mount.set_tracking(True)
    start = _time.monotonic()
    await mount.pulse_guide("W", 150)
    assert _time.monotonic() - start >= 0.15


@pytest.mark.parametrize("setup,match", [
    ("parked", "parked"),
    ("nudging", "nudge"),
])
async def test_pulse_refusals(setup: str, match: str) -> None:
    mount, _ = await _connected()
    if setup == "nudging":
        await mount.start_move("N", "centering")
    with pytest.raises(ValueError, match=match):
        await mount.pulse_guide("W", 100)


async def test_pulse_refused_while_one_runs_on_the_same_axis_but_not_the_other() -> None:
    mount, _ = await _connected()
    await mount.unpark()
    await mount.set_tracking(True)
    task = await _mid_pulse(mount, "W")
    with pytest.raises(ValueError, match="already running"):
        await mount.pulse_guide("E", 50)
    await mount.pulse_guide("N", 30)  # Dec is free
    await task


@pytest.mark.parametrize("direction,ms", [("X", 100), ("N", 0), ("N", 10_001)])
async def test_pulse_rejects_bad_arguments(direction: str, ms: int) -> None:
    mount, _ = await _connected()
    await mount.unpark()
    with pytest.raises(ValueError):
        await mount.pulse_guide(direction, ms)


async def test_stop_during_a_pulse_wins() -> None:
    """Stop mid-pulse must not be undone by the pulse restoring tracking afterwards."""
    mount, ctrl = await _connected(guide_rate=1.0)
    await mount.unpark()
    await mount.set_tracking(True)
    task = await _mid_pulse(mount, "E", ms=120)  # RA paused, will "resume tracking" at the end
    await mount.stop()
    await task
    assert not ctrl.axes[1].running
    assert (await mount.get_status()).is_tracking is False


async def test_guide_rate_is_validated_on_connect() -> None:
    ctrl = _FakeController()
    with pytest.raises(ValueError, match="guide_rate"):
        await EqmodMount(port="/dev/fake", baudrate=9600, guide_rate=2.0,
                         transport_factory=lambda p, b: ctrl).connect()


async def test_diagnostics_report_guide_rate_and_pulses() -> None:
    mount, _ = await _connected(guide_rate=0.8)
    diag = await mount.diagnostics()
    assert diag["guide_rate"] == 0.8 and diag["pulsing"] == []


# --- Meridian limit (RA axis past counterweight-horizontal, either way) ---

def _ra_counts(mech_deg: float) -> int:
    """Raw RA counts for a mechanical RA axis angle (90 deg = counterweight horizontal)."""
    return round(mech_deg / 360.0 * CPR)


async def _settle() -> None:
    import asyncio
    for _ in range(20):
        await asyncio.sleep(0)


@pytest.mark.parametrize("degrees", [-1.0, 61.0])
async def test_meridian_limit_is_validated(degrees: float) -> None:
    ctrl = _FakeController()
    with pytest.raises(ValueError, match="meridian_limit_deg"):
        await EqmodMount(port="/dev/fake", baudrate=9600, meridian_limit_deg=degrees,
                         transport_factory=lambda p, b: ctrl).connect()
    mount, _ = await _connected()
    with pytest.raises(ValueError, match="meridian_limit_deg"):
        await mount.set_meridian_limit(degrees)


async def test_flip_beyond_the_limit_is_refused_before_moving() -> None:
    mount, ctrl = await _connected()
    star = _star(2.0, 20.0)  # West side after a flip would be 30 deg past the meridian
    await mount.slew(star)
    ctrl.log.clear()
    with pytest.raises(ValueError, match="meridian limit"):
        await mount.meridian_flip()
    assert not any(cmd.startswith(":J") for cmd in ctrl.log)
    assert (await mount.get_status()).pier_side == "East"


async def test_flip_within_the_limit_is_allowed() -> None:
    mount, _ = await _connected()
    await mount.set_meridian_limit(40.0)
    await mount.slew(_star(2.0, 20.0))
    await mount.meridian_flip()
    assert (await mount.get_status()).pier_side == "West"


async def test_slew_takes_the_other_pier_side_when_the_natural_one_is_past_the_limit() -> None:
    from plugins.eqmod.geometry import SyncOffset

    mount, ctrl = await _connected()
    await mount.set_meridian_limit(0.0)
    # Just east of the meridian: naturally West side at axis angle 5.9h, which the sync offset
    # turns into 6.1h mechanically, past a zero limit. East side is -5.9h mechanically.
    mount._geometry.offset = SyncOffset(-0.2, 0.0)
    await mount.slew(_star(-0.1, 20.0))
    assert (await mount.get_status()).pier_side == "East"
    assert abs(mount._geometry.mechanical_ra_axis_h(ctrl.axes[1].position)) <= 6.0


async def test_park_and_park_position_beyond_the_limit_are_refused() -> None:
    mount, ctrl = await _connected()
    ctrl.axes[1].position = _ra_counts(115.0)
    with pytest.raises(ValueError, match="meridian limit"):
        await mount.set_park_position()
    mount._park_counts = (_ra_counts(-115.0), 0)
    ctrl.log.clear()
    with pytest.raises(ValueError, match="meridian limit"):
        await mount.park()
    assert not any(cmd.startswith(":J") for cmd in ctrl.log)


async def test_tracking_cannot_start_past_the_western_limit_but_can_past_the_eastern_one() -> None:
    mount, ctrl = await _connected()
    ctrl.axes[1].position = _ra_counts(111.0)
    with pytest.raises(ValueError, match="Meridian limit"):
        await mount.set_tracking(True)
    assert not ctrl.axes[1].running
    ctrl.axes[1].position = _ra_counts(-111.0)
    await mount.set_tracking(True)  # tracking turns the axis back toward the counterweight-down side
    assert ctrl.axes[1].running


async def test_tracking_into_the_limit_is_stopped() -> None:
    mount, ctrl = await _connected()
    ctrl.axes[1].position = _ra_counts(100.0)
    await mount.set_tracking(True)
    await mount._enforce_meridian_limit()
    assert ctrl.axes[1].running  # still inside
    ctrl.axes[1].position = _ra_counts(110.01)  # tracked into the limit
    await mount._enforce_meridian_limit()
    assert not ctrl.axes[1].running
    assert (await mount.get_status()).is_tracking is False


@pytest.mark.parametrize("mech_deg,direction", [(110.5, "W"), (-110.5, "E")])
async def test_nudge_past_the_limit_is_refused(mech_deg: float, direction: str) -> None:
    mount, ctrl = await _connected()
    ctrl.axes[1].position = _ra_counts(mech_deg)
    with pytest.raises(ValueError, match="Meridian limit"):
        await mount.start_move(direction, "centering")
    assert not ctrl.axes[1].running


async def test_nudge_back_from_the_limit_is_allowed() -> None:
    mount, ctrl = await _connected()
    ctrl.axes[1].position = _ra_counts(110.5)
    await mount.start_move("E", "centering")
    assert ctrl.axes[1].running and ctrl.axes[1].ccw is True
    await mount.stop_move()


async def test_dec_nudges_ignore_the_meridian_limit() -> None:
    mount, ctrl = await _connected()
    ctrl.axes[1].position = _ra_counts(115.0)
    await mount.start_move("N", "centering")
    assert ctrl.axes[2].running


async def test_westward_nudge_is_stopped_at_the_limit_and_tracking_stays_off() -> None:
    mount, ctrl = await _connected()
    ctrl.axes[1].position = _ra_counts(109.8)  # within the stop margin: the guard fires at once
    await mount.set_tracking(True)
    await mount.start_move("W", "centering")
    await _settle()
    assert not ctrl.axes[1].running
    status = await mount.get_status()
    assert status.is_tracking is False and status.is_slewing is False


async def test_eastward_nudge_is_stopped_at_the_limit_and_tracking_resumes() -> None:
    mount, ctrl = await _connected()
    ctrl.axes[1].position = _ra_counts(-109.8)
    await mount.set_tracking(True)
    await mount.start_move("E", "centering")
    await _settle()
    ra = ctrl.axes[1]
    assert ra.running and ra.ccw is False  # back to tracking, westward
    assert ra.period == step_period_for_rate(SIDEREAL_DEG_PER_SEC, CPR, TIMER_FREQ)
    assert (await mount.get_status()).is_slewing is False


async def test_nudge_guard_is_timed_from_the_room_left(monkeypatch) -> None:
    import asyncio

    delays: list[float] = []
    real_sleep = asyncio.sleep

    async def _record(delay: float, *args) -> None:
        delays.append(delay)
        await real_sleep(3600) if delay > 1 else await real_sleep(0)

    mount, ctrl = await _connected()
    ctrl.axes[1].position = _ra_counts(100.0)
    monkeypatch.setattr(mount_module.asyncio, "sleep", _record)
    await mount.start_move("W", "centering")
    await real_sleep(0)
    speed = 16.0 * SIDEREAL_DEG_PER_SEC
    assert delays[-1] == pytest.approx((10.0 - mount_module.LIMIT_STOP_MARGIN_DEG) / speed, rel=1e-3)
    guard = mount._limit_guard
    await mount.stop_move()  # a normal stop cancels the guard
    await real_sleep(0)
    assert guard is not None and guard.cancelled() and mount._limit_guard is None


async def test_diagnostics_report_the_meridian_margin() -> None:
    mount, ctrl = await _connected(meridian_limit_deg=15.0)
    ctrl.axes[1].position = _ra_counts(-100.0)
    diag = await mount.diagnostics()
    assert diag["meridian_limit_deg"] == 15.0
    assert diag["ra_axis_margin_deg"] == pytest.approx(5.0, abs=1e-3)
