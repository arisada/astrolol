"""Python-level access to the target plugin's favorites, for other components.

Registered as ``app.state.target_favorites`` (e.g. the sequencer resolves favorite
targets through it). Reads the persisted settings on each call, so edits are seen.
"""

from __future__ import annotations

from typing import Any

from astrolol.plugins.target.models import FavoriteTarget, TargetSettings


class FavoritesService:
    def __init__(self, profile_store: Any) -> None:
        self._profile_store = profile_store

    def list(self) -> list[FavoriteTarget]:
        if self._profile_store is None:
            return []
        raw = self._profile_store.get_user_settings().plugin_settings.get("target", {})
        return TargetSettings(**raw).favorites

    def get(self, favorite_id: str | None) -> FavoriteTarget | None:
        return next((f for f in self.list() if f.id == favorite_id), None)
