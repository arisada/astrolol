"""What drives an inventory item: an INDI or INDIGO driver, or the plugin behind its adapter.

Worked out from what the item stores, each time the inventory is listed, so it is never stale.
"""
from __future__ import annotations

from astrolol.devices.registry import DeviceRegistry
from astrolol.equipment.models import EquipmentItem


def device_source(item: EquipmentItem, registry: DeviceRegistry) -> str | None:
    """"indi", "indigo", a plugin id, or None (not a device, or an adapter nothing provides now)."""
    if not hasattr(item, "adapter_key"):
        return None
    driver = getattr(item, "indi_driver", None)
    if driver:
        # INDIGO names every driver indigo_*; INDI's are indi_* (or anything else).
        return "indigo" if driver.rsplit("/", 1)[-1].startswith("indigo_") else "indi"
    adapter = item.adapter_key
    if not adapter:
        return None
    if adapter in registry.sources:
        return registry.sources[adapter]
    return "indi" if adapter.startswith("indi_") else None


def with_source(item: EquipmentItem, registry: DeviceRegistry) -> EquipmentItem:
    if not hasattr(item, "source"):
        return item
    return item.model_copy(update={"source": device_source(item, registry)})


def without_source(item: EquipmentItem) -> EquipmentItem:
    """The item as it is saved: the source is the server's to say."""
    return item.model_copy(update={"source": None}) if getattr(item, "source", None) else item
