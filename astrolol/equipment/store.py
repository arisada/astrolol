"""JSON-backed equipment inventory store.

Same design as ProfileStore: single-process, no locking needed.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from astrolol.equipment.models import EquipmentItem

if TYPE_CHECKING:
    pass

# Pydantic type adapter for the discriminated union
from pydantic import TypeAdapter

_item_adapter: TypeAdapter[EquipmentItem] = TypeAdapter(EquipmentItem)

_SCHEMA_VERSION = 1


class EquipmentStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._items: dict[str, EquipmentItem] = {}
        self._load()

    # --- Persistence ---

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            if data.get("schema_version") != _SCHEMA_VERSION:
                # Incompatible schema — start with empty inventory
                return
            self._items = {
                raw["id"]: _item_adapter.validate_python(raw)
                for raw in data.get("items", [])
            }
        except Exception:
            pass  # corrupt file — start fresh

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "items": [
                _item_adapter.dump_python(item, mode="json")
                for item in self._items.values()
            ],
        }
        self._path.write_text(json.dumps(payload, indent=2))

    # --- CRUD ---

    def list(self) -> list[EquipmentItem]:
        return list(self._items.values())

    def get(self, item_id: str) -> EquipmentItem:
        item = self._items.get(item_id)
        if item is None:
            raise KeyError(item_id)
        return item

    def create(self, item: EquipmentItem) -> EquipmentItem:
        self._items[item.id] = item  # type: ignore[union-attr]
        self._save()
        return item

    def update(self, item: EquipmentItem) -> EquipmentItem:
        item_id = item.id  # type: ignore[union-attr]
        if item_id not in self._items:
            raise KeyError(item_id)
        self._items[item_id] = item
        self._save()
        return item

    def delete(self, item_id: str) -> None:
        if item_id not in self._items:
            raise KeyError(item_id)
        del self._items[item_id]
        self._save()
