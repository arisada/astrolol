import asyncio
from dataclasses import dataclass, field
from typing import Any

import structlog

from astrolol.core.errors import (
    AdapterNotFoundError,
    DeviceAlreadyConnectedError,
    DeviceConnectionError,
    DeviceKindError,
    DeviceNotFoundError,
)
from astrolol.core.events import (
    DeviceConnected,
    DeviceDisconnected,
    DeviceStateChanged,
    EventBus,
    FocuserPositionUpdated,
    MountCoordsUpdated,
)
from astrolol.devices.base import ICamera, IFocuser, IFilterWheel, IMount, IRotator
from astrolol.devices.base.models import DeviceState
from astrolol.devices.config import DeviceConfig
from astrolol.devices.registry import DeviceRegistry

logger = structlog.get_logger()

CONNECT_TIMEOUT = 30.0  # seconds
WATCHDOG_INTERVAL = 30.0  # seconds between ping checks
WATCHDOG_PING_TIMEOUT = 10.0  # seconds to wait for ping response

# Device kinds where only one instance may be active at a time.
# Connecting a new device of a singleton kind evicts any existing device of that kind.
_SINGLETON_KINDS: frozenset[str] = frozenset({"mount"})


@dataclass
class ConnectedDevice:
    config: DeviceConfig
    instance: Any  # ICamera | IMount | IFocuser | IFilterWheel | IRotator
    state: DeviceState = DeviceState.CONNECTED
    companions: list[str] = field(default_factory=list)
    primary_id: str | None = None
    _watchdog: asyncio.Task | None = field(default=None, repr=False)


@dataclass
class DeviceManager:
    registry: DeviceRegistry
    event_bus: EventBus
    _devices: dict[str, ConnectedDevice] = field(default_factory=dict)

    # --- Public API ---

    async def connect(self, config: DeviceConfig) -> str:
        """
        Instantiate and connect a device adapter from config.
        Returns the device_id on success.
        Raises AdapterNotFoundError, DeviceAlreadyConnectedError, DeviceConnectionError.
        """
        log = logger.bind(device_id=config.device_id, kind=config.kind, adapter=config.adapter_key)

        if config.device_id in self._devices:
            raise DeviceAlreadyConnectedError(
                f"Device '{config.device_id}' is already connected."
            )

        if config.kind in _SINGLETON_KINDS:
            existing = [
                did for did, entry in self._devices.items()
                if entry.config.kind == config.kind
            ]
            for did in existing:
                log.info("device.evicting_singleton", evicted_id=did, kind=config.kind)
                try:
                    await self.disconnect(did)
                except Exception as exc:
                    log.warning("device.evict_failed", evicted_id=did, error=str(exc))

        adapter_class = self._lookup_adapter(config)
        instance = adapter_class(**config.params)

        await self._publish_state_change(
            config, DeviceState.DISCONNECTED, DeviceState.CONNECTING
        )
        log.info("device.connecting")

        try:
            await asyncio.wait_for(instance.connect(), timeout=CONNECT_TIMEOUT)
        except asyncio.TimeoutError:
            await self._publish_state_change(
                config, DeviceState.CONNECTING, DeviceState.ERROR
            )
            raise DeviceConnectionError(
                f"Device '{config.device_id}' timed out after {CONNECT_TIMEOUT}s during connect."
            )
        except Exception as exc:
            await self._publish_state_change(
                config, DeviceState.CONNECTING, DeviceState.ERROR
            )
            raise DeviceConnectionError(
                f"Device '{config.device_id}' failed to connect: {exc}"
            ) from exc

        entry = ConnectedDevice(config=config, instance=instance)
        self._devices[config.device_id] = entry
        self._start_watchdog(config.device_id)
        await self.event_bus.publish(
            DeviceConnected(device_kind=config.kind, device_key=config.device_id)
        )
        await self._publish_state_change(
            config, DeviceState.CONNECTING, DeviceState.CONNECTED
        )
        log.info("device.connected")

        # Wire real-time property listeners for adapters that support them.
        # Duck-typed so non-INDI adapters (FakeMount, FakeFocuser, etc.) are unaffected.
        _device_id = config.device_id
        _bus = self.event_bus
        if hasattr(instance, "set_position_listener"):
            def _on_position(pos: int, _did: str = _device_id) -> None:
                asyncio.create_task(
                    _bus.publish(FocuserPositionUpdated(device_id=_did, position=pos))
                )
            instance.set_position_listener(_on_position)

        if hasattr(instance, "set_coords_listener"):
            def _on_coords(
                ra: float | None, dec: float | None,
                ra_jnow: float | None, dec_jnow: float | None,
                alt: float | None = None, az: float | None = None,
                pier_side: str | None = None,
                hour_angle: float | None = None, lst: float | None = None,
                _did: str = _device_id,
            ) -> None:
                asyncio.create_task(
                    _bus.publish(MountCoordsUpdated(
                        device_id=_did, ra=ra, dec=dec,
                        ra_jnow=ra_jnow, dec_jnow=dec_jnow,
                        alt=alt, az=az, pier_side=pier_side,
                        hour_angle=hour_angle, lst=lst,
                    ))
                )
            instance.set_coords_listener(_on_coords)

        # Companion discovery — only for primary devices (not companions themselves)
        if entry.primary_id is None and self.registry.companion_discoverer is not None:
            try:
                companion_configs = await self.registry.companion_discoverer(config)
                for companion_config in companion_configs:
                    try:
                        companion_id = await self._connect_companion(companion_config, config.device_id)
                        entry.companions.append(companion_id)
                    except Exception as exc:
                        log.warning(
                            "device.companion_connect_failed",
                            companion_id=companion_config.device_id,
                            error=str(exc),
                        )
            except Exception as exc:
                log.warning("device.companion_discovery_failed", error=str(exc))

        return config.device_id

    async def disconnect(self, device_id: str) -> None:
        """
        Disconnect and remove a device. Safe to call even if the device is unresponsive —
        the instance is always removed from the manager regardless of disconnect() outcome.
        Companions are disconnected first before the primary.
        """
        entry = self._get_entry(device_id)
        log = logger.bind(device_id=device_id, kind=entry.config.kind)
        log.info("device.disconnecting")

        await self._cancel_watchdog(entry)

        # Disconnect companions first
        for companion_id in list(entry.companions):
            try:
                await self._disconnect_device(companion_id)
            except Exception as exc:
                log.warning("device.companion_disconnect_error", companion_id=companion_id, error=str(exc))

        try:
            await asyncio.wait_for(entry.instance.disconnect(), timeout=CONNECT_TIMEOUT)
        except Exception as exc:
            log.warning("device.disconnect_error", error=str(exc))
        finally:
            del self._devices[device_id]
            await self.event_bus.publish(
                DeviceDisconnected(device_kind=entry.config.kind, device_key=device_id)
            )
            log.info("device.disconnected")

    async def soft_disconnect(self, device_id: str) -> None:
        """Disconnect device hardware but keep it registered so it can be reconnected.

        The device entry remains in the manager with state=DISCONNECTED.
        """
        entry = self._get_entry(device_id)
        log = logger.bind(device_id=device_id, kind=entry.config.kind)
        log.info("device.disconnecting")

        await self._cancel_watchdog(entry)

        try:
            await asyncio.wait_for(entry.instance.disconnect(), timeout=CONNECT_TIMEOUT)
        except Exception as exc:
            log.warning("device.disconnect_error", error=str(exc))

        entry.state = DeviceState.DISCONNECTED
        await self._publish_state_change(entry.config, DeviceState.CONNECTED, DeviceState.DISCONNECTED)
        await self.event_bus.publish(
            DeviceDisconnected(device_kind=entry.config.kind, device_key=device_id)
        )
        log.info("device.disconnected")

    async def reconnect(self, device_id: str) -> None:
        """Reconnect a previously soft-disconnected device without re-registering it."""
        entry = self._get_entry(device_id)
        if entry.state == DeviceState.CONNECTED:
            raise DeviceAlreadyConnectedError(f"Device '{device_id}' is already connected.")

        # Clear pre_connect_props before reconnecting so that stale or over-broad
        # property overrides don't clobber driver-managed state (e.g. alignment data).
        # INDI drivers keep their in-memory state while indiserver is running and
        # restore from ~/.indi/ after a restart — let them manage their own config.
        #
        # TODO: replace with a proper per-device allowlist of properties that are
        # safe to push on each session (e.g. DEVICE_PORT).  Until then, any
        # pre-connect overrides must be set manually through the INDI properties
        # panel; INDI will then persist them in its own config.
        if hasattr(entry.instance, "_pre_connect_props"):
            entry.instance._pre_connect_props = None

        log = logger.bind(device_id=device_id, kind=entry.config.kind)
        await self._publish_state_change(entry.config, DeviceState.DISCONNECTED, DeviceState.CONNECTING)
        log.info("device.connecting")

        try:
            await asyncio.wait_for(entry.instance.connect(), timeout=CONNECT_TIMEOUT)
        except asyncio.TimeoutError:
            entry.state = DeviceState.ERROR
            await self._publish_state_change(entry.config, DeviceState.CONNECTING, DeviceState.ERROR)
            raise DeviceConnectionError(
                f"Device '{device_id}' timed out after {CONNECT_TIMEOUT}s during reconnect."
            )
        except Exception as exc:
            entry.state = DeviceState.ERROR
            await self._publish_state_change(entry.config, DeviceState.CONNECTING, DeviceState.ERROR)
            raise DeviceConnectionError(
                f"Device '{device_id}' failed to reconnect: {exc}"
            ) from exc

        entry.state = DeviceState.CONNECTED
        self._start_watchdog(device_id)
        await self.event_bus.publish(
            DeviceConnected(device_kind=entry.config.kind, device_key=device_id)
        )
        await self._publish_state_change(entry.config, DeviceState.CONNECTING, DeviceState.CONNECTED)
        log.info("device.connected")

    def get_camera(self, device_id: str) -> ICamera:
        return self._get_typed(device_id, "camera")  # type: ignore[return-value]

    def get_mount(self, device_id: str) -> IMount:
        return self._get_typed(device_id, "mount")  # type: ignore[return-value]

    def get_focuser(self, device_id: str) -> IFocuser:
        return self._get_typed(device_id, "focuser")  # type: ignore[return-value]

    def get_filter_wheel(self, device_id: str) -> IFilterWheel:
        return self._get_typed(device_id, "filter_wheel")  # type: ignore[return-value]

    def get_rotator(self, device_id: str) -> IRotator:
        return self._get_typed(device_id, "rotator")  # type: ignore[return-value]

    def get_config(self, device_id: str) -> DeviceConfig:
        """Return the full DeviceConfig (including params) for a connected device."""
        return self._get_entry(device_id).config

    def list_connected(self) -> list[dict]:
        return [
            {
                "device_id": d.config.device_id,
                "kind": d.config.kind,
                "adapter_key": d.config.adapter_key,
                "state": d.state.value,
                "companions": list(d.companions),
                "primary_id": d.primary_id,
                "driver_name": d.config.driver_name or d.config.params.get("device_name"),
            }
            for d in self._devices.values()
        ]

    # --- Internal helpers ---

    async def _watchdog_worker(self, device_id: str) -> None:
        """Periodically ping a device and update its state on failure/recovery."""
        try:
            while True:
                await asyncio.sleep(WATCHDOG_INTERVAL)
                entry = self._devices.get(device_id)
                if entry is None:
                    return
                if entry.state not in (DeviceState.CONNECTED, DeviceState.ERROR):
                    continue
                try:
                    ok = await asyncio.wait_for(
                        entry.instance.ping(), timeout=WATCHDOG_PING_TIMEOUT
                    )
                except Exception:
                    ok = False

                if not ok and entry.state == DeviceState.CONNECTED:
                    logger.warning("device.watchdog_failed", device_id=device_id, kind=entry.config.kind)
                    entry.state = DeviceState.ERROR
                    await self._publish_state_change(entry.config, DeviceState.CONNECTED, DeviceState.ERROR)
                elif ok and entry.state == DeviceState.ERROR:
                    logger.info("device.watchdog_recovered", device_id=device_id, kind=entry.config.kind)
                    entry.state = DeviceState.CONNECTED
                    await self._publish_state_change(entry.config, DeviceState.ERROR, DeviceState.CONNECTED)
        except asyncio.CancelledError:
            pass

    def _start_watchdog(self, device_id: str) -> None:
        entry = self._devices.get(device_id)
        if entry is None:
            return
        if entry._watchdog is not None and not entry._watchdog.done():
            entry._watchdog.cancel()
        entry._watchdog = asyncio.create_task(
            self._watchdog_worker(device_id), name=f"watchdog:{device_id}"
        )

    async def _cancel_watchdog(self, entry: ConnectedDevice) -> None:
        if entry._watchdog is not None and not entry._watchdog.done():
            entry._watchdog.cancel()
            try:
                await entry._watchdog
            except asyncio.CancelledError:
                pass
            entry._watchdog = None

    async def _connect_companion(self, config: DeviceConfig, primary_id: str) -> str:
        """Connect a companion device and mark it as belonging to primary_id."""
        log = logger.bind(device_id=config.device_id, kind=config.kind, primary_id=primary_id)

        if config.device_id in self._devices:
            raise DeviceAlreadyConnectedError(
                f"Companion device '{config.device_id}' is already connected."
            )

        adapter_class = self._lookup_adapter(config)
        instance = adapter_class(**config.params)

        await self._publish_state_change(config, DeviceState.DISCONNECTED, DeviceState.CONNECTING)
        log.info("device.companion_connecting")

        try:
            await asyncio.wait_for(instance.connect(), timeout=CONNECT_TIMEOUT)
        except asyncio.TimeoutError:
            await self._publish_state_change(config, DeviceState.CONNECTING, DeviceState.ERROR)
            raise DeviceConnectionError(
                f"Companion device '{config.device_id}' timed out after {CONNECT_TIMEOUT}s."
            )
        except Exception as exc:
            await self._publish_state_change(config, DeviceState.CONNECTING, DeviceState.ERROR)
            raise DeviceConnectionError(
                f"Companion device '{config.device_id}' failed to connect: {exc}"
            ) from exc

        entry = ConnectedDevice(config=config, instance=instance, primary_id=primary_id)
        self._devices[config.device_id] = entry
        self._start_watchdog(config.device_id)
        await self.event_bus.publish(
            DeviceConnected(device_kind=config.kind, device_key=config.device_id)
        )
        await self._publish_state_change(config, DeviceState.CONNECTING, DeviceState.CONNECTED)
        log.info("device.companion_connected")
        return config.device_id

    async def _disconnect_device(self, device_id: str) -> None:
        """Disconnect and remove a device without companion handling (used for companions)."""
        if device_id not in self._devices:
            return
        entry = self._devices[device_id]
        log = logger.bind(device_id=device_id, kind=entry.config.kind)
        await self._cancel_watchdog(entry)
        try:
            await asyncio.wait_for(entry.instance.disconnect(), timeout=CONNECT_TIMEOUT)
        except Exception as exc:
            log.warning("device.disconnect_error", error=str(exc))
        finally:
            del self._devices[device_id]
            await self.event_bus.publish(
                DeviceDisconnected(device_kind=entry.config.kind, device_key=device_id)
            )

    def _lookup_adapter(self, config: DeviceConfig) -> Any:
        pool = {
            "camera": self.registry.cameras,
            "mount": self.registry.mounts,
            "focuser": self.registry.focusers,
            "filter_wheel": self.registry.filter_wheels,
            "rotator": self.registry.rotators,
            "indi": self.registry.indi_raws,
        }.get(config.kind, {})

        adapter_class = pool.get(config.adapter_key)
        if adapter_class is None:
            raise AdapterNotFoundError(
                f"No adapter '{config.adapter_key}' registered for kind '{config.kind}'. "
                f"Available: {list(pool)}"
            )
        return adapter_class

    def _get_entry(self, device_id: str) -> ConnectedDevice:
        try:
            return self._devices[device_id]
        except KeyError:
            raise DeviceNotFoundError(f"No connected device with id '{device_id}'.")

    def _get_typed(self, device_id: str, expected_kind: str) -> Any:
        entry = self._get_entry(device_id)
        if entry.config.kind != expected_kind:
            raise DeviceKindError(
                f"Device '{device_id}' is a {entry.config.kind}, not a {expected_kind}."
            )
        return entry.instance

    async def _publish_state_change(
        self,
        config: DeviceConfig,
        old: DeviceState,
        new: DeviceState,
    ) -> None:
        await self.event_bus.publish(
            DeviceStateChanged(
                device_kind=config.kind,
                device_key=config.device_id,
                old_state=old,
                new_state=new,
            )
        )
