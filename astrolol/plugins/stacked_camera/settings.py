"""Settings of the stacked-camera plugin, kept in ``UserSettings.plugin_settings``."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StackedCameraSettings(BaseModel):
    sub_exposure: float = Field(
        default=2.0,
        gt=0,
        le=60,
        description="Seconds of each short frame; the guide camera gets one per sub-exposure",
    )
