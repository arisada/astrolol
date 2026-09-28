import asyncio

import pytest

from astrolol.core.events import (
    MountOperationFailed,
    MountParked,
    MountSlewAborted,
    MountSlewCompleted,
    MountSlewStarted,
    MountSynced,
    MountTrackingChanged,
    MountUnparked,
)
import astropy.units as u
from astropy.coordinates import SkyCoord

from astrolol.devices.base.models import TrackingMode
from astrolol.devices.config import DeviceConfig
from astrolol.devices.manager import DeviceManager
from astrolol.equipment.models import SiteItem
from astrolol.mount.manager import MountManager
from tests.conftest import FakeMount


# ---------------------------------------------------------------------------
# Helper mount that records set_location / set_time_utc calls
# ---------------------------------------------------------------------------

class _SiteAwareMount(FakeMount):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.site_lat: float | None = None
        self.site_lon: float | None = None
        self.site_alt: float | None = None
        self.time_set_count: int = 0

    async def set_location(self, lat: float, lon: float, alt: float) -> None:
        self.site_lat = lat
        self.site_lon = lon
        self.site_alt = alt

    async def set_time_utc(self) -> None:
        self.time_set_count += 1


class _FailingSiteMount(FakeMount):
    """Mount whose set_location / set_time_utc always raise."""
    async def set_location(self, lat: float, lon: float, alt: float) -> None:
        raise RuntimeError("driver rejected location")

    async def set_time_utc(self) -> None:
        raise RuntimeError("driver rejected time")


async def connected_mount(manager: DeviceManager, device_id: str = "mount1") -> str:
    config = DeviceConfig(device_id=device_id, kind="mount", adapter_key="fake_mount")
    return await manager.connect(config)


# --- slew ---

@pytest.mark.asyncio
async def test_slew_returns_immediately(mount_manager: MountManager, manager: DeviceManager) -> None:
    await connected_mount(manager)
    coord = SkyCoord(ra=6.0 * u.hourangle, dec=45.0 * u.deg, frame="icrs")
    await mount_manager.set_target("mount1", coord)
    await mount_manager.slew("mount1")
    # should not block — task runs in background
    status = await mount_manager.get_status("mount1")
    assert status.ra is not None


@pytest.mark.asyncio
async def test_slew_publishes_started_and_completed(
    mount_manager: MountManager, manager: DeviceManager, event_bus
) -> None:
    await connected_mount(manager)
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    coord = SkyCoord(ra=6.0 * u.hourangle, dec=45.0 * u.deg, frame="icrs")
    await mount_manager.set_target("mount1", coord)
    await mount_manager.slew("mount1")

    # consume MountTargetSet before the slew events
    started = await asyncio.wait_for(q.get(), timeout=2.0)
    while started.type == "mount.target_set":
        started = await asyncio.wait_for(q.get(), timeout=2.0)
    assert isinstance(started, MountSlewStarted)
    assert started.ra == pytest.approx(90.0)   # 6h × 15 = 90°

    # wait for background task to finish
    ctrl = mount_manager._controllers["mount1"]
    if ctrl._active_task:
        await asyncio.wait_for(ctrl._active_task, timeout=2.0)

    completed = await asyncio.wait_for(q.get(), timeout=2.0)
    assert isinstance(completed, MountSlewCompleted)
    assert completed.dec == pytest.approx(45.0)


@pytest.mark.asyncio
async def test_slew_updates_position(
    mount_manager: MountManager, manager: DeviceManager
) -> None:
    await connected_mount(manager)
    coord = SkyCoord(ra=12.5 * u.hourangle, dec=-30.0 * u.deg, frame="icrs")
    await mount_manager.set_target("mount1", coord)
    await mount_manager.slew("mount1")

    ctrl = mount_manager._controllers["mount1"]
    if ctrl._active_task:
        await asyncio.wait_for(ctrl._active_task, timeout=2.0)

    status = await mount_manager.get_status("mount1")
    assert status.ra == pytest.approx(12.5)
    assert status.dec == pytest.approx(-30.0)


@pytest.mark.asyncio
async def test_slew_without_target_raises(
    mount_manager: MountManager, manager: DeviceManager
) -> None:
    await connected_mount(manager)
    with pytest.raises(ValueError, match="target"):
        await mount_manager.slew("mount1")


@pytest.mark.asyncio
async def test_slew_while_busy_raises(
    mount_manager: MountManager, manager: DeviceManager
) -> None:
    await connected_mount(manager)
    coord = SkyCoord(ra=1.0 * u.hourangle, dec=0.0 * u.deg, frame="icrs")
    await mount_manager.set_target("mount1", coord)
    await mount_manager.slew("mount1")
    with pytest.raises(ValueError, match="busy"):
        await mount_manager.slew("mount1")
    await mount_manager.stop("mount1")


# --- stop ---

@pytest.mark.asyncio
async def test_stop_aborts_slew(
    mount_manager: MountManager, manager: DeviceManager, event_bus
) -> None:
    await connected_mount(manager)
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    await mount_manager.set_target("mount1", SkyCoord(ra=1.0 * u.hourangle, dec=0.0 * u.deg, frame="icrs"))
    await mount_manager.slew("mount1")
    await mount_manager.stop("mount1")

    events = []
    while not q.empty():
        events.append(q.get_nowait())

    types = [e.type for e in events]
    assert "mount.slew_aborted" in types


@pytest.mark.asyncio
async def test_stop_when_idle_is_safe(
    mount_manager: MountManager, manager: DeviceManager
) -> None:
    await connected_mount(manager)
    # Should not raise
    await mount_manager.stop("mount1")


# --- park / unpark ---

@pytest.mark.asyncio
async def test_park_publishes_parked_event(
    mount_manager: MountManager, manager: DeviceManager, event_bus
) -> None:
    await connected_mount(manager)
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    await mount_manager.park("mount1")
    ctrl = mount_manager._controllers["mount1"]
    if ctrl._active_task:
        await asyncio.wait_for(ctrl._active_task, timeout=2.0)

    events = []
    while not q.empty():
        events.append(q.get_nowait())

    assert any(isinstance(e, MountParked) for e in events)


@pytest.mark.asyncio
async def test_park_sets_parked_state(
    mount_manager: MountManager, manager: DeviceManager
) -> None:
    await connected_mount(manager)
    await mount_manager.park("mount1")
    ctrl = mount_manager._controllers["mount1"]
    if ctrl._active_task:
        await asyncio.wait_for(ctrl._active_task, timeout=2.0)

    status = await mount_manager.get_status("mount1")
    assert status.is_parked is True


@pytest.mark.asyncio
async def test_unpark(mount_manager: MountManager, manager: DeviceManager) -> None:
    await connected_mount(manager)
    await mount_manager.park("mount1")
    ctrl = mount_manager._controllers["mount1"]
    if ctrl._active_task:
        await asyncio.wait_for(ctrl._active_task, timeout=2.0)

    await mount_manager.unpark("mount1")
    status = await mount_manager.get_status("mount1")
    assert status.is_parked is False


# --- sync ---

@pytest.mark.asyncio
async def test_sync_publishes_event(
    mount_manager: MountManager, manager: DeviceManager, event_bus
) -> None:
    await connected_mount(manager)
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    coord = SkyCoord(ra=5.5 * u.hourangle, dec=22.0 * u.deg, frame="icrs")
    await mount_manager.sync("mount1", coord)

    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert isinstance(event, MountSynced)
    assert event.ra == pytest.approx(5.5 * 15)   # 5.5h × 15 = 82.5°


# --- tracking ---

@pytest.mark.asyncio
async def test_set_tracking_publishes_event(
    mount_manager: MountManager, manager: DeviceManager, event_bus
) -> None:
    await connected_mount(manager)
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    await mount_manager.set_tracking("mount1", True)
    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert isinstance(event, MountTrackingChanged)
    assert event.tracking is True

    status = await mount_manager.get_status("mount1")
    assert status.is_tracking is True


@pytest.mark.asyncio
async def test_disable_tracking(
    mount_manager: MountManager, manager: DeviceManager
) -> None:
    await connected_mount(manager)
    await mount_manager.set_tracking("mount1", True)
    await mount_manager.set_tracking("mount1", False)
    status = await mount_manager.get_status("mount1")
    assert status.is_tracking is False


@pytest.mark.asyncio
async def test_set_tracking_with_mode_event_carries_mode(
    mount_manager: MountManager, manager: DeviceManager, event_bus
) -> None:
    """MountTrackingChanged event should include the requested mode."""
    await connected_mount(manager)
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    await mount_manager.set_tracking("mount1", True, TrackingMode.LUNAR)
    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert isinstance(event, MountTrackingChanged)
    assert event.tracking is True
    assert event.mode == TrackingMode.LUNAR


@pytest.mark.asyncio
async def test_set_tracking_mode_passed_to_adapter(
    mount_manager: MountManager, manager: DeviceManager
) -> None:
    """The adapter's set_tracking receives the mode value."""
    from tests.conftest import FakeMount
    await connected_mount(manager)
    fake: FakeMount = manager._devices["mount1"].instance  # type: ignore[union-attr]

    await mount_manager.set_tracking("mount1", True, TrackingMode.SOLAR)
    assert fake.last_tracking_mode == TrackingMode.SOLAR


@pytest.mark.asyncio
async def test_set_tracking_no_mode_passes_none(
    mount_manager: MountManager, manager: DeviceManager
) -> None:
    """Omitting mode passes None to the adapter (sidereal default stays with driver)."""
    from tests.conftest import FakeMount
    await connected_mount(manager)
    fake: FakeMount = manager._devices["mount1"].instance  # type: ignore[union-attr]

    await mount_manager.set_tracking("mount1", True)
    assert fake.last_tracking_mode is None


# --- unpark event ---

@pytest.mark.asyncio
async def test_unpark_publishes_event(
    mount_manager: MountManager, manager: DeviceManager, event_bus
) -> None:
    """unpark() should publish MountUnparked."""
    await connected_mount(manager)
    await mount_manager.park("mount1")
    ctrl = mount_manager._controllers["mount1"]
    if ctrl._active_task:
        await asyncio.wait_for(ctrl._active_task, timeout=2.0)

    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    await mount_manager.unpark("mount1")
    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert isinstance(event, MountUnparked)
    assert event.device_id == "mount1"


# --- operation_failed events ---

@pytest.mark.asyncio
async def test_slew_error_publishes_operation_failed(
    mount_manager: MountManager, manager: DeviceManager, event_bus
) -> None:
    """A slew that raises an exception publishes MountSlewAborted + MountOperationFailed."""
    from unittest.mock import patch

    await connected_mount(manager)
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    async def failing_slew(_target):
        raise RuntimeError("motor fault")

    await mount_manager.set_target("mount1", SkyCoord(ra=1.0 * u.hourangle, dec=0.0 * u.deg, frame="icrs"))
    with patch.object(
        manager._devices["mount1"].instance, "slew", side_effect=failing_slew
    ):
        await mount_manager.slew("mount1")
        ctrl = mount_manager._controllers["mount1"]
        if ctrl._active_task:
            await asyncio.wait_for(ctrl._active_task, timeout=2.0)

    events = []
    while not q.empty():
        events.append(q.get_nowait())

    types = [e.type for e in events]
    assert "mount.slew_aborted" in types
    assert "mount.operation_failed" in types

    failed = next(e for e in events if isinstance(e, MountOperationFailed))
    assert failed.operation == "slew"
    assert "motor fault" in failed.reason


@pytest.mark.asyncio
async def test_slew_timeout_publishes_operation_failed(
    mount_manager: MountManager, manager: DeviceManager, event_bus
) -> None:
    """A slew that hits asyncio.TimeoutError publishes MountOperationFailed."""
    from unittest.mock import patch

    await connected_mount(manager)
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    async def timing_out(_target):
        raise asyncio.TimeoutError()

    await mount_manager.set_target("mount1", SkyCoord(ra=1.0 * u.hourangle, dec=0.0 * u.deg, frame="icrs"))
    with patch.object(
        manager._devices["mount1"].instance, "slew", side_effect=timing_out
    ):
        await mount_manager.slew("mount1")
        ctrl = mount_manager._controllers["mount1"]
        if ctrl._active_task:
            await asyncio.wait_for(ctrl._active_task, timeout=2.0)

    events = []
    while not q.empty():
        events.append(q.get_nowait())

    failed = [e for e in events if isinstance(e, MountOperationFailed)]
    assert len(failed) == 1
    assert failed[0].operation == "slew"
    assert "timed out" in failed[0].reason


@pytest.mark.asyncio
async def test_park_error_publishes_operation_failed(
    mount_manager: MountManager, manager: DeviceManager, event_bus
) -> None:
    """An exception in park() should publish MountOperationFailed."""
    from unittest.mock import patch

    await connected_mount(manager)
    q = event_bus.subscribe()
    while not q.empty():
        await q.get()

    async def failing_park():
        raise RuntimeError("hardware fault")

    with patch.object(manager._devices["mount1"].instance, "park", side_effect=failing_park):
        await mount_manager.park("mount1")
        ctrl = mount_manager._controllers["mount1"]
        if ctrl._active_task:
            await asyncio.wait_for(ctrl._active_task, timeout=2.0)

    events = []
    while not q.empty():
        events.append(q.get_nowait())

    failed = [e for e in events if isinstance(e, MountOperationFailed)]
    assert len(failed) == 1
    assert failed[0].operation == "park"
    assert "hardware fault" in failed[0].reason


# --- push_site_data ---

@pytest.mark.asyncio
async def test_push_site_data_sets_location_and_time(
    manager: DeviceManager, event_bus
) -> None:
    """push_site_data pushes both location and UTC time when location is provided."""
    manager.registry.register_mount("site_mount", _SiteAwareMount)  # type: ignore[arg-type]
    await manager.connect(DeviceConfig(device_id="m1", kind="mount", adapter_key="site_mount"))
    mm = MountManager(device_manager=manager, event_bus=event_bus)

    loc = SiteItem(name="Paris", latitude=48.85, longitude=2.35, altitude=35.0)
    await mm.push_site_data("m1", loc)

    fake: _SiteAwareMount = manager._devices["m1"].instance  # type: ignore[assignment]
    assert fake.site_lat == pytest.approx(48.85)
    assert fake.site_lon == pytest.approx(2.35)
    assert fake.site_alt == pytest.approx(35.0)
    assert fake.time_set_count == 1


@pytest.mark.asyncio
async def test_push_site_data_no_location_still_sets_time(
    manager: DeviceManager, event_bus
) -> None:
    """push_site_data always sets UTC time even when location is None."""
    manager.registry.register_mount("site_mount", _SiteAwareMount)  # type: ignore[arg-type]
    await manager.connect(DeviceConfig(device_id="m1", kind="mount", adapter_key="site_mount"))
    mm = MountManager(device_manager=manager, event_bus=event_bus)

    await mm.push_site_data("m1", location=None)

    fake: _SiteAwareMount = manager._devices["m1"].instance  # type: ignore[assignment]
    assert fake.site_lat is None     # location not pushed
    assert fake.time_set_count == 1  # time was pushed


@pytest.mark.asyncio
async def test_push_site_data_tolerates_driver_failure(
    manager: DeviceManager, event_bus
) -> None:
    """push_site_data does not raise when the driver rejects time/location."""
    manager.registry.register_mount("failing_site_mount", _FailingSiteMount)  # type: ignore[arg-type]
    await manager.connect(DeviceConfig(device_id="m1", kind="mount", adapter_key="failing_site_mount"))
    mm = MountManager(device_manager=manager, event_bus=event_bus)

    loc = SiteItem(name="Test Site", latitude=48.85, longitude=2.35, altitude=35.0)
    # Must not raise even though the mount raises on both calls
    await mm.push_site_data("m1", loc)


@pytest.mark.asyncio
async def test_push_site_data_skips_mount_without_site_methods(
    manager: DeviceManager, event_bus
) -> None:
    """push_site_data is silent when the adapter has no set_location / set_time_utc."""
    # FakeMount has neither method → push_site_data should be a no-op without raising
    await manager.connect(DeviceConfig(device_id="m1", kind="mount", adapter_key="fake_mount"))
    mm = MountManager(device_manager=manager, event_bus=event_bus)

    loc = SiteItem(name="Test Site", latitude=48.85, longitude=2.35, altitude=35.0)
    await mm.push_site_data("m1", loc)  # no-op, no exception


# --- start_automation / stop_automation ---

@pytest.mark.asyncio
async def test_stop_automation_cancels_the_task(manager: DeviceManager, event_bus) -> None:
    await manager.connect(DeviceConfig(device_id="m1", kind="mount", adapter_key="fake_mount"))
    mm = MountManager(device_manager=manager, event_bus=event_bus)

    mm.start_automation("m1")
    task = mm._automation_tasks["m1"]
    assert not task.done()

    mm.stop_automation("m1")

    assert "m1" not in mm._automation_tasks
    await asyncio.sleep(0)  # let the cancellation propagate
    assert task.cancelled()


@pytest.mark.asyncio
async def test_stop_automation_forgets_guard_state(manager: DeviceManager, event_bus) -> None:
    """Regression: leftover _auto_park_last/_auto_flip_triggered/_horizon_triggered entries
    for a device_id that's gone are a (small) leak of their own alongside the task itself."""
    await manager.connect(DeviceConfig(device_id="m1", kind="mount", adapter_key="fake_mount"))
    mm = MountManager(device_manager=manager, event_bus=event_bus)
    mm.start_automation("m1")
    mm._auto_park_last["m1"] = (3, 0)
    mm._auto_flip_triggered.add("m1")
    mm._horizon_triggered.add("m1")

    mm.stop_automation("m1")

    assert "m1" not in mm._auto_park_last
    assert "m1" not in mm._auto_flip_triggered
    assert "m1" not in mm._horizon_triggered


def test_stop_automation_is_idempotent(mount_manager: MountManager) -> None:
    """Safe to call even when automation was never started for this device_id."""
    mount_manager.stop_automation("never-started")  # must not raise


@pytest.mark.asyncio
async def test_disconnect_stops_mount_automation(manager: DeviceManager, event_bus) -> None:
    """Regression: DeviceManager.disconnect() left the automation loop running forever,
    silently polling a device_id that no longer exists in the manager."""
    await manager.connect(DeviceConfig(device_id="m1", kind="mount", adapter_key="fake_mount"))
    mm = MountManager(device_manager=manager, event_bus=event_bus)
    mm.start_automation("m1")
    task = mm._automation_tasks["m1"]

    await manager.disconnect("m1")
    mm.stop_automation("m1")  # what api/devices.py's disconnect endpoint now does

    assert "m1" not in mm._automation_tasks
    await asyncio.sleep(0)
    assert task.cancelled()


# --- pulse guiding (optional adapter capability) ---

class _GuidingMount(FakeMount):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pulses: list[tuple[str, int]] = []

    async def pulse_guide(self, direction: str, duration_ms: int) -> None:
        self.pulses.append((direction, duration_ms))


@pytest.mark.asyncio
async def test_pulse_guide_calls_the_adapter(mount_manager: MountManager, manager: DeviceManager) -> None:
    manager.registry.register_mount("guiding", _GuidingMount)  # type: ignore[arg-type]
    await manager.connect(DeviceConfig(device_id="g", kind="mount", adapter_key="guiding"))
    await mount_manager.pulse_guide("g", "W", 250)
    assert manager.get_mount("g").pulses == [("W", 250)]


@pytest.mark.asyncio
async def test_pulse_guide_unsupported_adapter(mount_manager: MountManager, manager: DeviceManager) -> None:
    await connected_mount(manager)
    with pytest.raises(ValueError, match="does not support pulse guiding"):
        await mount_manager.pulse_guide("mount1", "N", 100)


@pytest.mark.asyncio
async def test_pulse_guide_refused_while_slewing(mount_manager: MountManager, manager: DeviceManager) -> None:
    manager.registry.register_mount("guiding", _GuidingMount)  # type: ignore[arg-type]
    await manager.connect(DeviceConfig(device_id="g", kind="mount", adapter_key="guiding"))
    await mount_manager.set_target("g", SkyCoord(ra=1.0 * u.hourangle, dec=0.0 * u.deg, frame="icrs"))
    await mount_manager.slew("g")
    with pytest.raises(ValueError, match="busy"):
        await mount_manager.pulse_guide("g", "N", 100)
    await mount_manager.stop("g")


# --- Limits: horizon (core) and meridian (pushed to adapters that enforce it) ---

from astrolol.config.user_settings import MountDeviceSettings, UserSettings  # noqa: E402
from astrolol.devices.base.models import MountStatus  # noqa: E402

_PARIS = SiteItem(name="Paris", latitude=48.85, longitude=2.35, altitude=35.0)


class _SettingsStore:
    def __init__(self, **mount_settings) -> None:
        self.settings = UserSettings(mount_settings={"m1": MountDeviceSettings(**mount_settings).model_dump()})

    def get_user_settings(self) -> UserSettings:
        return self.settings


class _AltitudeMount(FakeMount):
    """Reports a settable altitude and records the meridian limit it was given."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.alt: float | None = 30.0
        self.meridian_limit: float | None = None

    async def get_status(self) -> MountStatus:
        return (await super().get_status()).model_copy(update={"alt": self.alt})

    async def set_meridian_limit(self, degrees: float) -> None:
        self.meridian_limit = degrees


async def _limits_setup(manager: DeviceManager, event_bus, site=_PARIS, **mount_settings):
    manager.registry.register_mount("alt_mount", _AltitudeMount)  # type: ignore[arg-type]
    await manager.connect(DeviceConfig(device_id="m1", kind="mount", adapter_key="alt_mount"))
    mm = MountManager(
        device_manager=manager, event_bus=event_bus,
        profile_store=_SettingsStore(**mount_settings),  # type: ignore[arg-type]
        site_provider=lambda: site,
    )
    fake: _AltitudeMount = manager._devices["m1"].instance  # type: ignore[assignment]
    return mm, fake


_NEVER_RISES = SkyCoord(ra=0 * u.deg, dec=-80 * u.deg)      # from Paris
_CIRCUMPOLAR = SkyCoord(ra=37.95 * u.deg, dec=89.26 * u.deg)  # Polaris, alt ~ latitude


@pytest.mark.asyncio
async def test_slew_below_the_horizon_is_refused(manager: DeviceManager, event_bus) -> None:
    mm, _ = await _limits_setup(manager, event_bus)
    await mm.set_target("m1", _NEVER_RISES)
    with pytest.raises(ValueError, match="below the horizon limit"):
        await mm.slew("m1")
    assert not mm._get_or_create("m1").is_busy


@pytest.mark.asyncio
async def test_horizon_limit_altitude_is_configurable(manager: DeviceManager, event_bus) -> None:
    mm, _ = await _limits_setup(manager, event_bus, horizon_min_alt_deg=55.0)
    await mm.set_target("m1", _CIRCUMPOLAR)
    with pytest.raises(ValueError, match="55"):
        await mm.slew("m1")


@pytest.mark.asyncio
async def test_slew_above_the_horizon_is_allowed(manager: DeviceManager, event_bus) -> None:
    mm, _ = await _limits_setup(manager, event_bus)
    await mm.set_target("m1", _CIRCUMPOLAR)
    await mm.slew("m1")
    await mm._get_or_create("m1")._active_task


@pytest.mark.asyncio
async def test_without_a_site_the_horizon_is_not_checked(manager: DeviceManager, event_bus) -> None:
    mm, _ = await _limits_setup(manager, event_bus, site=None)
    await mm.set_target("m1", _NEVER_RISES)
    await mm.slew("m1")
    await mm._get_or_create("m1")._active_task


@pytest.mark.asyncio
async def test_sinking_below_the_horizon_stops_tracking_once(manager: DeviceManager, event_bus) -> None:
    mm, fake = await _limits_setup(manager, event_bus, horizon_min_alt_deg=10.0)
    fake._tracking = True
    fake.alt = 12.0
    await mm._check_automation("m1")
    assert fake._tracking  # above the limit

    fake.alt = 9.5
    await mm._check_automation("m1")
    assert not fake._tracking

    fake._tracking = True  # user restarts tracking below the limit: not fought
    await mm._check_automation("m1")
    assert fake._tracking

    fake.alt = 10.5  # inside the re-arm band: still not re-armed
    await mm._check_automation("m1")
    fake.alt = 9.0
    await mm._check_automation("m1")
    assert fake._tracking

    fake.alt = 11.5  # clearly above: re-armed
    await mm._check_automation("m1")
    fake.alt = 9.0
    await mm._check_automation("m1")
    assert not fake._tracking


@pytest.mark.asyncio
async def test_horizon_action_park(manager: DeviceManager, event_bus) -> None:
    mm, fake = await _limits_setup(manager, event_bus, horizon_action="park")
    fake._tracking, fake.alt = True, -0.5
    await mm._check_automation("m1")
    await mm._get_or_create("m1")._active_task
    assert fake._parked


@pytest.mark.asyncio
@pytest.mark.parametrize("action,tracking", [("none", True), ("stop_tracking", False)])
async def test_horizon_action_none_or_idle_mount_does_nothing(
    manager: DeviceManager, event_bus, action: str, tracking: bool
) -> None:
    mm, fake = await _limits_setup(manager, event_bus, horizon_action=action)
    fake._tracking, fake.alt = tracking, -5.0
    await mm._check_automation("m1")
    assert fake._tracking is tracking and not fake._parked


@pytest.mark.asyncio
async def test_apply_limits_pushes_the_meridian_limit(manager: DeviceManager, event_bus) -> None:
    mm, fake = await _limits_setup(manager, event_bus, meridian_limit_deg=12.5)
    await mm.apply_limits("m1")
    assert fake.meridian_limit == 12.5


@pytest.mark.asyncio
async def test_apply_limits_skips_adapters_without_a_meridian_limit(manager: DeviceManager, event_bus) -> None:
    await connected_mount(manager, "m2")
    mm = MountManager(device_manager=manager, event_bus=event_bus)
    await mm.apply_limits("m2")  # FakeMount has no set_meridian_limit: silently skipped
    await mm.apply_limits("missing")  # unknown device: logged, not raised


# --- Meridian flip needs the pier side, not just the hour angle ---

from astrolol.mount.manager import meridian_flip_due  # noqa: E402


@pytest.mark.parametrize("pier,ha,due", [
    ("West", 1.3, True),     # tracked past the meridian on the eastern-target side
    ("East", 1.3, False),    # already flipped: normal for a western target
    ("West", -2.0, False),   # normal for an eastern target
    ("East", -0.5, True),    # counterweight up on the east side
    ("West", 23.0, False),   # HA given as 0..24 is normalised (-1h)
    (None, 1.0, None),
    ("West", None, None),
])
def test_meridian_flip_due(pier, ha, due) -> None:
    assert meridian_flip_due(pier, ha) is due


@pytest.mark.asyncio
async def test_manual_flip_from_the_normal_side_is_refused(manager: DeviceManager, event_bus) -> None:
    mm, fake = await _limits_setup(manager, event_bus)
    fake._pier_side, fake._hour_angle = "East", 1.3
    with pytest.raises(ValueError, match="No meridian flip needed"):
        await mm.meridian_flip("m1")
    assert not mm._get_or_create("m1").is_busy

    fake._pier_side = "West"
    await mm.meridian_flip("m1")
    await mm._get_or_create("m1")._active_task
    assert fake._pier_side == "East"


@pytest.mark.asyncio
@pytest.mark.parametrize("pier,flips", [("West", True), ("East", False)])
async def test_auto_flip_only_from_the_wrong_side(
    manager: DeviceManager, event_bus, pier: str, flips: bool
) -> None:
    mm, fake = await _limits_setup(manager, event_bus, auto_flip_enabled=True, auto_flip_ha_hours=1.0)
    fake._pier_side, fake._hour_angle = pier, 1.2
    await mm._check_automation("m1")
    task = mm._get_or_create("m1")._active_task
    assert (task is not None) is flips
    if task is not None:
        await task
        assert fake._pier_side == "East"


@pytest.mark.asyncio
async def test_auto_flip_suspended(manager: DeviceManager, event_bus) -> None:
    """A sequencer suspends the automatic flip while it owns the mount; nesting is counted."""
    mm, fake = await _limits_setup(manager, event_bus, auto_flip_enabled=True, auto_flip_ha_hours=1.0)
    fake._pier_side, fake._hour_angle = "West", 1.2
    with mm.suspend_auto_flip("m1"):
        with mm.suspend_auto_flip("m1"):
            pass
        await mm._check_automation("m1")
        assert mm._get_or_create("m1")._active_task is None
    await mm._check_automation("m1")
    task = mm._get_or_create("m1")._active_task
    assert task is not None
    await task
