"""Polar-alignment wizard event models."""
from __future__ import annotations

from typing import Literal

from astrolol.core.events.models import BaseEvent


class PolarAlignWizardStarted(BaseEvent):
    type: Literal["polar_align.wizard_started"] = "polar_align.wizard_started"
    run_id: str


class PolarAlignPointStarted(BaseEvent):
    type: Literal["polar_align.point_started"] = "polar_align.point_started"
    run_id: str
    index: int


class PolarAlignPointSolved(BaseEvent):
    type: Literal["polar_align.point_solved"] = "polar_align.point_solved"
    run_id: str
    index: int
    solved_ra_hours: float
    solved_dec_deg: float


class PolarAlignFitCompleted(BaseEvent):
    type: Literal["polar_align.fit_completed"] = "polar_align.fit_completed"
    run_id: str
    alt_error_arcmin: float
    az_error_arcmin: float


class PolarAlignErrorUpdated(BaseEvent):
    """Emitted on each CONVERGING-phase recheck, as the user turns the alt/az knobs."""
    type: Literal["polar_align.error_updated"] = "polar_align.error_updated"
    run_id: str
    alt_error_arcmin: float
    az_error_arcmin: float


class PolarAlignWizardCompleted(BaseEvent):
    type: Literal["polar_align.wizard_completed"] = "polar_align.wizard_completed"
    run_id: str


class PolarAlignWizardFailed(BaseEvent):
    type: Literal["polar_align.wizard_failed"] = "polar_align.wizard_failed"
    run_id: str
    reason: str


class PolarAlignWizardCancelled(BaseEvent):
    type: Literal["polar_align.wizard_cancelled"] = "polar_align.wizard_cancelled"
    run_id: str
