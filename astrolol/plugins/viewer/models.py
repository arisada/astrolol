"""Pydantic models for the viewer plugin — API request/response shapes.

``ImageRecord`` mirrors the ``images`` table in ``index.py`` almost exactly; kept as a
separate model (rather than reading rows straight into it) so the SQL schema can evolve
without silently changing the API contract.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from astrolol.core.events import BaseEvent


class ViewerSettings(BaseModel):
    """Persisted under UserSettings.plugin_settings["viewer"]."""
    library_dir: str = ""  # resolved to a real default on first use if left blank


class ImageRecord(BaseModel):
    id: str
    path: str
    size_bytes: int
    mtime: float
    captured_at: datetime
    captured_at_estimated: bool
    frame_type: str
    object_name: str
    exposure_s: float | None = None
    gain: int | None = None
    binning: int | None = None
    filter_name: str = ""
    camera_name: str = ""
    telescope_name: str = ""
    ra_deg: float | None = None
    dec_deg: float | None = None
    coord_source: str | None = None
    ccd_temp: float | None = None
    width: int | None = None
    height: int | None = None
    night: str
    bg_median: float | None = None
    star_count: int | None = None
    hfr: float | None = None
    indexed_at: datetime


class ImageListResponse(BaseModel):
    items: list[ImageRecord]
    total: int
    next_cursor: str | None = None


class GroupSummary(BaseModel):
    frame_type: str
    object_name: str
    filter_name: str
    camera_name: str
    exposure_s: float | None = None
    binning: int | None = None
    gain: int | None = None
    night: str
    count: int
    total_exposure_s: float
    first_captured_at: datetime
    last_captured_at: datetime
    representative_id: str
    ra_deg: float | None = None
    dec_deg: float | None = None
    sky_cell_ra: float | None = None
    sky_cell_dec: float | None = None


class GroupListResponse(BaseModel):
    items: list[GroupSummary]
    total: int


class Facets(BaseModel):
    objects: list[str]
    frame_types: list[str]
    filters: list[str]
    cameras: list[str]


class RollupRow(BaseModel):
    object_name: str
    frame_count: int
    total_exposure_s: float
    nights: int
    first_captured_at: datetime
    last_captured_at: datetime


class RescanResult(BaseModel):
    added: int
    updated: int
    removed: int
    duration_s: float


class RenderRequest(BaseModel):
    mode: str = Field(default="auto", pattern="^(auto|linear)$")
    target_bg: float = Field(default=0.25, gt=0.0, lt=1.0)
    shadows: float = Field(default=-2.8, ge=-10.0, le=0.0)
    color: bool = True
    linked: bool = False
    quality: int = Field(default=85, ge=1, le=100)


class UnrejectRequest(BaseModel):
    relative_path: str


class RejectedItem(BaseModel):
    relative_path: str
    size_bytes: int
    mtime: float


class LibraryStatus(BaseModel):
    library_dir: str
    total_bytes: int
    free_bytes: int
    image_count: int
    rescanning: bool
    rejected_count: int
    rejected_bytes: int


# --- Events ---

class ViewerIndexChangedEvent(BaseEvent):
    """Coalesced — emitted at most once per second during a burst of index writes
    (a multi-file rescan, or several ExposureCompleted events in quick succession),
    rather than once per file."""
    type: Literal["viewer.index_changed"] = "viewer.index_changed"


class ViewerRescanStartedEvent(BaseEvent):
    type: Literal["viewer.rescan_started"] = "viewer.rescan_started"
    library_dir: str


class ViewerRescanProgressEvent(BaseEvent):
    type: Literal["viewer.rescan_progress"] = "viewer.rescan_progress"
    scanned: int


class ViewerRescanCompletedEvent(BaseEvent):
    type: Literal["viewer.rescan_completed"] = "viewer.rescan_completed"
    added: int = 0
    updated: int = 0
    removed: int = 0
    duration_s: float = 0.0
    cancelled: bool = False
    error: str | None = None
