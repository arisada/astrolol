"""Simple JSON-backed profile store.  No concurrency issues — FastAPI is single-process."""
from __future__ import annotations

import json
from pathlib import Path

from astrolol.profiles.models import Profile


class ProfileStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._profiles: dict[str, Profile] = {}
        self._last_active_id: str | None = None
        self._load()

    # --- Persistence ---

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            self._profiles = {
                p["id"]: Profile.model_validate(p)
                for p in data.get("profiles", [])
            }
            self._last_active_id = data.get("last_active_profile_id")
        except Exception:
            pass  # corrupt file — start fresh

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "profiles": [p.model_dump() for p in self._profiles.values()],
            "last_active_profile_id": self._last_active_id,
        }
        self._path.write_text(json.dumps(payload, indent=2))

    # --- CRUD ---

    def list(self) -> list[Profile]:
        return list(self._profiles.values())

    def get(self, profile_id: str) -> Profile:
        p = self._profiles.get(profile_id)
        if p is None:
            raise KeyError(profile_id)
        return p

    def create(self, profile: Profile) -> Profile:
        self._profiles[profile.id] = profile
        self._save()
        return profile

    def update(self, profile: Profile) -> Profile:
        if profile.id not in self._profiles:
            raise KeyError(profile.id)
        self._profiles[profile.id] = profile
        self._save()
        return profile

    def delete(self, profile_id: str) -> None:
        if profile_id not in self._profiles:
            raise KeyError(profile_id)
        del self._profiles[profile_id]
        self._save()

    # --- Last active profile ---

    def get_last_active_id(self) -> str | None:
        return self._last_active_id

    def set_last_active_id(self, profile_id: str | None) -> None:
        self._last_active_id = profile_id
        self._save()
