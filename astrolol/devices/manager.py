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
)
from astrolol.devices.base import ICamera, IFocuser, IMount
from astrolol.devices.base.models import DeviceState
from astrolol.devices.config import DeviceConfig
from astrolol.devices.registry import DeviceRegistry

logger = structlog.get_logger()

CONNECT_TIMEOUT = 30.0  # seconds

# Device kinds where only one instance may be active at a time.
# Connecting a new device of a singleton kind evicts any existing device of that kind.
_SINGLETON_KINDS: frozenset[str] = frozenset({"mount"})


@dataclass
class ConnectedDevice:
    config: DeviceConfig
    instance: Any  # ICamera | IMount | IFocuser
    state: DeviceState = DeviceState.CONNECTED


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

        self._devices[config.device_id] = ConnectedDevice(config=config, instance=instance)
        await self.event_bus.publish(
            DeviceConnected(device_kind=config.kind, device_key=config.device_id)
        )
        await self._publish_state_change(
            config, DeviceState.CONNECTING, DeviceState.CONNECTED
        )
        log.info("device.connected")
        return config.device_id

    async def disconnect(self, device_id: str) -> None:
        """
        Disconnect and remove a device. Safe to call even if the device is unresponsive —
        the instance is always removed from the manager regardless of disconnect() outcome.
        """
        entry = self._get_entry(device_id)
        log = logger.bind(device_id=device_id, kind=entry.config.kind)
        log.info("device.disconnecting")

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

    def get_config(self, device_id: str) -> DeviceConfig:
        """Return the full DeviceConfig (including params) for a connected device."""
        return self._get_entry(device_id).config

    def list_connected(self) -> list[dict[str, str]]:
        return [
            {
                "device_id": d.config.device_id,
                "kind": d.config.kind,
                "adapter_key": d.config.adapter_key,
                "state": d.state.value,
            }
            for d in self._devices.values()
        ]

    # --- Internal helpers ---

    def _lookup_adapter(self, config: DeviceConfig) -> Any:
        pool = {
            "camera": self.registry.cameras,
            "mount": self.registry.mounts,
            "focuser": self.registry.focusers,
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
