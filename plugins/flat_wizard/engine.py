"""Flat wizard engine: per-filter trial-and-error exposure solving.

Algorithm (per filter)
-----------------------
1. Change to the filter (if a filter wheel is configured).
2. Take a short, unsaved trial exposure at the current trial duration.
3. Read the mean ADU level and the sensor's full-scale ADU from the imager's last
   exposure statistics, and compute ``ratio = mean / full_scale``.
4. If saturated (``ratio >= saturation_pct``), halve the duration and retry — the flat
   response is otherwise assumed linear in exposure time, but a clipped frame's mean is
   not a reliable predictor of the correct scale-down.
5. If ``ratio`` is within ``tolerance_pct`` of ``target_pct``, the filter is solved.
6. Otherwise scale the duration proportionally (``duration *= target_ratio / ratio``)
   and retry, up to ``max_attempts``.

Once every filter has been attempted, one ``ImagingTask`` (frame_type="flat") covering
all solved filters is queued on the sequencer — this engine only ever takes short,
unsaved trial exposures; the sequencer runner shoots and saves the real flats.
"""
from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import FastAPI

from astrolol.core.events import EventBus
from plugins.flat_wizard.models import (
    FlatFilterResult,
    FlatTrial,
    FlatWizardAbortedEvent,
    FlatWizardCompletedEvent,
    FlatWizardConfig,
    FlatWizardFailedEvent,
    FlatWizardFilterFailedEvent,
    FlatWizardFilterSolvedEvent,
    FlatWizardFilterSpec,
    FlatWizardRun,
    FlatWizardStartedEvent,
    FlatWizardTrialEvent,
)

logger = structlog.get_logger()

_SATURATION_BACKOFF = 0.5  # multiply duration by this after a saturated trial
_NO_SIGNAL_JUMP = 5.0      # multiply duration by this when the trial measured ~zero signal
_SOLVED_DURATION_SIG_FIGS = 3  # the solved duration is queued/displayed to this many sig figs


def _round_significant(value: float, digits: int = _SOLVED_DURATION_SIG_FIGS) -> float:
    """Round *value* to *digits* significant figures (e.g. 10.123456 -> 10.1, 0.00012345 -> 0.000123).

    The trial-and-error search converges on an arbitrary float; nobody needs the 6th
    decimal of a flat exposure, and a round number is easier to sanity-check in the UI
    and in the queued sequencer task.
    """
    if value == 0:
        return 0.0
    magnitude = math.floor(math.log10(abs(value)))
    factor = 10 ** (digits - 1 - magnitude)
    return round(value * factor) / factor


class FlatWizardEngine:
    """Manages one flat-wizard run at a time.

    Holds the FastAPI app (not direct manager references) so the imager, filter wheel
    and sequencer are looked up lazily on each run — plugin setup order isn't
    guaranteed, and the sequencer in particular is itself a plugin.
    """

    def __init__(self, app: FastAPI, event_bus: EventBus) -> None:
        self._app = app
        self._bus = event_bus
        self._current_run: FlatWizardRun | None = None
        self._task: asyncio.Task | None = None

    @property
    def current_run(self) -> FlatWizardRun | None:
        return self._current_run

    def _state(self, name: str) -> Any:
        return getattr(self._app.state, name, None)

    async def start(self, config: FlatWizardConfig) -> FlatWizardRun:
        if self._task is not None and not self._task.done():
            raise ValueError("The flat wizard is already running. Call abort() first.")
        if self._state("sequencer") is None:
            raise ValueError("The sequencer plugin is not enabled — the flat wizard has nowhere to send the result.")

        run = FlatWizardRun(config=config, total_filters=len(config.filters))
        self._current_run = run
        self._task = asyncio.create_task(self._run(run), name=f"flat_wizard_{run.id}")
        return run

    async def abort(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _run(self, run: FlatWizardRun) -> None:
        config = run.config
        try:
            await self._bus.publish(FlatWizardStartedEvent(
                run_id=run.id, camera_id=config.camera_id, total_filters=run.total_filters,
            ))
            logger.info("flat_wizard.started", run_id=run.id, camera_id=config.camera_id)

            for index, spec in enumerate(config.filters):
                run.current_filter_index = index
                result = await self._solve_filter(run, spec, index)
                run.results.append(result)
                if result.status == "solved":
                    await self._bus.publish(FlatWizardFilterSolvedEvent(
                        run_id=run.id, filter_index=index, filter_name=spec.filter_name,
                        duration=result.solved_duration,  # type: ignore[arg-type]
                    ))
                    logger.info(
                        "flat_wizard.filter_solved", run_id=run.id, filter=spec.filter_name,
                        duration=result.solved_duration,
                    )
                else:
                    await self._bus.publish(FlatWizardFilterFailedEvent(
                        run_id=run.id, filter_index=index, filter_name=spec.filter_name,
                        error=result.error or "unknown error",
                    ))
                    logger.warning(
                        "flat_wizard.filter_failed", run_id=run.id, filter=spec.filter_name,
                        error=result.error,
                    )

            await self._queue_sequence(run)

            run.status = "completed" if any(r.status == "solved" for r in run.results) else "failed"
            if run.status == "failed":
                run.error = "No filter could be solved; nothing was queued."
            run.completed_at = datetime.now(timezone.utc)

            await self._bus.publish(FlatWizardCompletedEvent(run_id=run.id, task_id=run.task_id))
            logger.info("flat_wizard.completed", run_id=run.id, task_id=run.task_id, status=run.status)

        except asyncio.CancelledError:
            run.status = "aborted"
            run.completed_at = datetime.now(timezone.utc)
            await self._bus.publish(FlatWizardAbortedEvent(run_id=run.id))
            logger.info("flat_wizard.aborted", run_id=run.id)
            raise

        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            run.completed_at = datetime.now(timezone.utc)
            await self._bus.publish(FlatWizardFailedEvent(run_id=run.id, reason=str(exc)))
            logger.error("flat_wizard.failed", run_id=run.id, error=str(exc), exc_info=True)

    async def _solve_filter(
        self, run: FlatWizardRun, spec: FlatWizardFilterSpec, filter_index: int
    ) -> FlatFilterResult:
        config = run.config
        imager = self._state("imager_manager")
        if imager is None:
            return FlatFilterResult(filter_name=spec.filter_name, status="failed", error="Imager is not available")

        if spec.filter_name is not None:
            error = await self._select_filter(config, spec.filter_name)
            if error is not None:
                return FlatFilterResult(filter_name=spec.filter_name, status="failed", error=error)

        from astrolol.imaging.models import ExposureRequest

        target_ratio = config.target_pct / 100.0
        tolerance = config.tolerance_pct / 100.0
        saturation_ratio = config.saturation_pct / 100.0

        duration = config.seed_duration
        trials: list[FlatTrial] = []
        last_clamped: float | None = None

        for attempt in range(1, config.max_attempts + 1):
            clamped = max(config.min_duration, min(config.max_duration, duration))
            if last_clamped is not None and clamped == last_clamped:
                return FlatFilterResult(
                    filter_name=spec.filter_name, status="failed", trials=trials,
                    error=(
                        f"Stuck at the exposure-duration limit ({clamped:.3f}s) without reaching "
                        "the target ADU — adjust the flat panel brightness or widen the duration range."
                    ),
                )
            last_clamped = clamped
            duration = clamped

            req = ExposureRequest(
                duration=duration, gain=config.gain, binning=config.binning,
                frame_type="flat", save=False,
            )
            try:
                await imager.expose(config.camera_id, req)
            except Exception as exc:
                return FlatFilterResult(
                    filter_name=spec.filter_name, status="failed", trials=trials,
                    error=f"Trial exposure failed: {exc}",
                )

            stats = imager.get_last_stats(config.camera_id)
            if stats is None or stats.hist_max <= 0:
                return FlatFilterResult(
                    filter_name=spec.filter_name, status="failed", trials=trials,
                    error="No exposure statistics were available for the trial frame",
                )

            ratio = stats.mean / stats.hist_max
            saturated = ratio >= saturation_ratio
            trial = FlatTrial(
                attempt=attempt, duration=duration, mean_adu=stats.mean,
                full_scale_adu=stats.hist_max, ratio_pct=round(ratio * 100, 2), saturated=saturated,
            )
            trials.append(trial)
            await self._bus.publish(FlatWizardTrialEvent(
                run_id=run.id, filter_index=filter_index, filter_name=spec.filter_name,
                attempt=attempt, duration=duration, mean_adu=stats.mean,
                full_scale_adu=stats.hist_max, ratio_pct=trial.ratio_pct, saturated=saturated,
            ))
            logger.info(
                "flat_wizard.trial", run_id=run.id, filter=spec.filter_name, attempt=attempt,
                duration=round(duration, 4), ratio_pct=trial.ratio_pct, saturated=saturated,
            )

            if saturated:
                if duration <= config.min_duration:
                    return FlatFilterResult(
                        filter_name=spec.filter_name, status="failed", trials=trials,
                        error="Saturated even at the minimum exposure duration — reduce the flat panel brightness.",
                    )
                duration = duration * _SATURATION_BACKOFF
                continue

            if abs(ratio - target_ratio) <= tolerance:
                return FlatFilterResult(
                    filter_name=spec.filter_name, status="solved", trials=trials,
                    solved_duration=_round_significant(duration),
                )

            if ratio <= 1e-6:
                duration = duration * _NO_SIGNAL_JUMP
                continue

            duration = duration * (target_ratio / ratio)

        return FlatFilterResult(
            filter_name=spec.filter_name, status="failed", trials=trials,
            error=f"Did not converge to the target ADU within {config.max_attempts} attempts.",
        )

    async def _select_filter(self, config: FlatWizardConfig, filter_name: str) -> str | None:
        """Move the filter wheel to *filter_name*. Returns an error string, or None on success."""
        fwm = self._state("filter_wheel_manager")
        if config.filter_wheel_id is None or fwm is None:
            return f"No filter wheel configured, but filter '{filter_name}' was requested."
        try:
            status = await fwm.get_status(config.filter_wheel_id)
        except Exception as exc:
            return f"Could not read the filter wheel: {exc}"
        names = status.filter_names or []
        if filter_name not in names:
            return f"Filter '{filter_name}' is not in the wheel ({', '.join(names) or 'no names'})."
        slot = names.index(filter_name) + 1
        if status.current_slot == slot:
            return None
        try:
            await fwm.select_filter(config.filter_wheel_id, slot)
        except Exception as exc:
            return f"Changing to filter '{filter_name}' failed: {exc}"
        return None

    async def _queue_sequence(self, run: FlatWizardRun) -> None:
        """Build one flat-frame ImagingTask from every solved filter and queue it."""
        from astrolol.core.sequencer.models import ExposureGroup, ImagingTask, Lane, TargetRef

        config = run.config
        groups = [
            ExposureGroup(
                filter_name=spec.filter_name, duration=result.solved_duration,  # type: ignore[arg-type]
                count=spec.count, binning=config.binning, gain=config.gain, frame_type="flat",
            )
            for spec, result in zip(config.filters, run.results)
            if result.status == "solved" and result.solved_duration is not None
        ]
        if not groups:
            return

        sequencer = self._state("sequencer")
        if sequencer is None:
            run.error = "The sequencer became unavailable before the result could be queued."
            return

        task = ImagingTask(
            name="Flats",
            target=TargetRef(kind="current", name="Flats"),
            lanes=[Lane(camera_id=config.camera_id, groups=groups)],
            slew=False,
            center=False,
            start_guiding=False,
            autofocus_at_start=False,
            dither_every=None,
            on_error="skip",
        )
        entry = await sequencer.add(task)
        run.task_id = entry.task.id
