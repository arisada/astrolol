"""Simple JSON-backed profile store.  No concurrency issues — FastAPI is single-process."""
from __future__ import annotations

import json
from pathlib import Path

from astrolol.config.user_settings import UserSettings
from astrolol.devices.base.models import Target
from astrolol.profiles.models import Profile

_DEFAULT_SETTINGS = UserSettings()


class ProfileStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._profiles: dict[str, Profile] = {}
        self._last_active_id: str | None = None
        self._mount_targets: dict[str, Target] = {}
        self._user_settings: UserSettings = _DEFAULT_SETTINGS
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
            self._mount_targets = {
                device_id: Target.model_validate(t)
                for device_id, t in data.get("mount_targets", {}).items()
            }
            # Pick up any UserSettings fields present in the JSON; unknown keys are
            # ignored and missing keys fall back to model defaults automatically.
            settings_data = {
                k: data[k] for k in UserSettings.model_fields if k in data
            }
            self._user_settings = UserSettings(**settings_data)
        except Exception:
            pass  # corrupt file — start fresh

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "profiles": [p.model_dump() for p in self._profiles.values()],
            "last_active_profile_id": self._last_active_id,
            "mount_targets": {k: t.model_dump(mode="json") for k, t in self._mount_targets.items()},
            # Spread all UserSettings fields so new fields are auto-persisted
            **self._user_settings.model_dump(),
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

    # --- Mount targets ---

    def get_mount_target(self, device_id: str) -> Target | None:
        return self._mount_targets.get(device_id)

    def set_mount_target(self, device_id: str, target: Target | None) -> None:
        """Remember (or, with None, forget) a mount's target so it survives a restart."""
        if target is None:
            if self._mount_targets.pop(device_id, None) is None:
                return
        else:
            self._mount_targets[device_id] = target
        self._save()

    # --- User settings ---

    def get_user_settings(self) -> UserSettings:
        return self._user_settings

    def update_user_settings(self, settings: UserSettings) -> UserSettings:
        self._user_settings = settings
        self._save()
        return self._user_settings
