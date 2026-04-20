"""SequenceRunner — the async state machine coroutine for the sequencer plugin."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from plugins.sequencer.events import (
    SequenceCancelled,
    SequenceCompleted,
    SequenceFailed,
    SequenceFrameCompleted,
    SequencePaused,
    SequenceResumed,
    SequenceStarted,
    SequenceStepChanged,
    SequenceTaskCompleted,
    SequenceTaskFailed,
)
from plugins.sequencer.models import (
    FilterExposure,
    ImagingTask,
    SequencerState,
    SequencerStatus,
    TaskStatus,
)
from plugins.sequencer.settings import SequencerSettings

if TYPE_CHECKING:
    from astrolol.core.events import EventBus

logger = structlog.get_logger()


class SequencerPausedError(Exception):
    """Raised internally to halt the runner in PAUSED state.

    The runner task stays alive; the frame loop blocks on _resume_event.
    """


# ---------------------------------------------------------------------------
# Progress persistence
# ---------------------------------------------------------------------------

class SequenceProgress:
    """Tracks frame completion per task/group and persists to disk atomically."""

    def __init__(self, state_path: Path) -> None:
        self._path = state_path
        self._data: dict[str, dict] = {}  # task_id → {done, group_frames}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
            if raw.get("schema_version") == 1:
                self._data = raw.get("tasks", {})
        except Exception:
            self._data = {}

    def frames_done(self, task_id: str, group_idx: int) -> int:
        frames = self._data.get(task_id, {}).get("group_frames", [])
        return frames[group_idx] if group_idx < len(frames) else 0

    def is_task_done(self, task_id: str) -> bool:
        return self._data.get(task_id, {}).get("done", False)

    def record_frame(self, task_id: str, group_idx: int) -> None:
        if task_id not in self._data:
            self._data[task_id] = {"done": False, "group_frames": []}
        frames = self._data[task_id]["group_frames"]
        while len(frames) <= group_idx:
            frames.append(0)
        frames[group_idx] += 1
        self._save()

    def mark_task_done(self, task_id: str) -> None:
        if task_id not in self._data:
            self._data[task_id] = {"done": True, "group_frames": []}
        else:
            self._data[task_id]["done"] = True
        self._save()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "tasks": self._data}
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        os.replace(str(tmp), str(self._path))

    def delete(self) -> None:
        if self._path.exists():
            self._path.unlink(missing_ok=True)
        self._data = {}


# ---------------------------------------------------------------------------
# SequenceRunner
# ---------------------------------------------------------------------------

class SequenceRunner:
    """Async state machine that drives the imaging task queue."""

    def __init__(
        self,
        event_bus: "EventBus",
        settings: SequencerSettings,
        state_path: Path,
    ) -> None:
        self._event_bus = event_bus
        self._settings = settings
        self._progress = SequenceProgress(state_path)

        # Queue
        self._queue: list[ImagingTask] = []
        self._task_status: dict[str, TaskStatus] = {}

        # Runtime state
        self._state: SequencerState = SequencerState.IDLE
        self._step_message: str | None = None
        self._error: str | None = None
        self._current_task_id: str | None = None
        self._current_task_name: str | None = None
        self._current_group_idx: int | None = None
        self._frames_done_in_group: int | None = None
        self._frames_total_in_group: int | None = None

        # Async control primitives
        self._run_lock = asyncio.Lock()
        self._run_task: asyncio.Task | None = None  # the active runner coroutine task
        self._running = False                        # True while _run_lock is held
        self._pause_requested = False
        self._pause_mode = "after_frame"
        self._resume_event = asyncio.Event()

        # App reference — set by SequencerPlugin.setup()
        self._app: Any = None

    def set_app(self, app: Any) -> None:
        self._app = app

    # ------------------------------------------------------------------
    # Managers — looked up lazily via app.state (guarded; plugin may be absent)
    # ------------------------------------------------------------------

    def _imager_manager(self) -> Any:
        return getattr(self._app.state, "imager_manager", None) if self._app else None

    def _mount_manager(self) -> Any:
        return getattr(self._app.state, "mount_manager", None) if self._app else None

    def _device_manager(self) -> Any:
        return getattr(self._app.state, "device_manager", None) if self._app else None

    def _phd2_client(self) -> Any:
        return getattr(self._app.state, "phd2_client", None) if self._app else None

    def _solve_manager(self) -> Any:
        return getattr(self._app.state, "solve_manager", None) if self._app else None

    def _filter_wheel_manager(self) -> Any:
        return getattr(self._app.state, "filter_wheel_manager", None) if self._app else None

    def _first_connected(self, kind: str) -> str | None:
        dm = self._device_manager()
        if dm is None:
            return None
        devices = [d for d in dm.list_connected() if d["kind"] == kind]
        return devices[0]["device_id"] if devices else None

    def _camera_id(self, task: ImagingTask) -> str | None:
        return task.camera_device_id or self._first_connected("camera")

    def _filter_wheel_id(self, task: ImagingTask) -> str | None:
        return task.filter_wheel_device_id or self._first_connected("filter_wheel")

    def _mount_id(self) -> str | None:
        return self._first_connected("mount")

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def add_task(self, task: ImagingTask, *, restore_progress: bool = True) -> None:
        self._queue.append(task)
        # Restore progress from saved state
        if restore_progress and self._progress.is_task_done(task.id):
            self._task_status[task.id] = TaskStatus.COMPLETED
        else:
            self._task_status[task.id] = TaskStatus.PENDING

    def get_task(self, task_id: str) -> ImagingTask | None:
        return next((t for t in self._queue if t.id == task_id), None)

    def get_task_status(self, task_id: str) -> TaskStatus | None:
        return self._task_status.get(task_id)

    def update_task(self, task_id: str, updated: ImagingTask) -> ImagingTask:
        if self._task_status.get(task_id) == TaskStatus.RUNNING:
            raise ValueError("Cannot modify a running task")
        idx = next((i for i, t in enumerate(self._queue) if t.id == task_id), None)
        if idx is None:
            raise KeyError(task_id)
        self._queue[idx] = updated
        if self._task_status.get(task_id) != TaskStatus.COMPLETED:
            self._task_status[task_id] = TaskStatus.PENDING
        return updated

    def delete_task(self, task_id: str) -> None:
        if task_id not in self._task_status:
            raise KeyError(task_id)
        if self._task_status.get(task_id) == TaskStatus.RUNNING:
            raise ValueError("Cannot delete a running task")
        self._queue = [t for t in self._queue if t.id != task_id]
        self._task_status.pop(task_id, None)

    def reorder_tasks(self, order: list[str]) -> None:
        """Reorder pending tasks according to the given ID list."""
        pending_map = {
            t.id: t for t in self._queue
            if self._task_status.get(t.id) == TaskStatus.PENDING
        }
        non_pending = [
            t for t in self._queue
            if self._task_status.get(t.id) != TaskStatus.PENDING
        ]
        reordered = [pending_map[tid] for tid in order if tid in pending_map]
        # Any pending tasks not mentioned in order stay at the end
        mentioned = set(order)
        rest = [t for t in self._queue if t.id in pending_map and t.id not in mentioned]
        self._queue = non_pending + reordered + rest

    def clear_pending(self) -> None:
        removed = {t.id for t in self._queue if self._task_status.get(t.id) == TaskStatus.PENDING}
        self._queue = [t for t in self._queue if t.id not in removed]
        for tid in removed:
            self._task_status.pop(tid, None)

    def list_tasks(self) -> list[ImagingTask]:
        return list(self._queue)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> SequencerStatus:
        tasks_done = sum(1 for s in self._task_status.values() if s == TaskStatus.COMPLETED)
        return SequencerStatus(
            state=self._state,
            current_task_id=self._current_task_id,
            current_task_name=self._current_task_name,
            current_group_idx=self._current_group_idx,
            frames_done=self._frames_done_in_group,
            frames_total=self._frames_total_in_group,
            step_message=self._step_message,
            error=self._error,
            queue_length=len(self._queue),
            tasks_done=tasks_done,
        )

    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Launch the runner task. Raises RuntimeError if already running."""
        if self._running:
            raise RuntimeError("Sequencer is already running")
        self._running = True
        self._error = None
        self._run_task = asyncio.create_task(self.run(), name="sequencer_run")

    def request_pause(self, mode: str = "after_frame") -> None:
        self._pause_requested = True
        self._pause_mode = mode

    def resume(self) -> None:
        self._resume_event.set()

    async def cancel(self) -> None:
        if self._run_task and not self._run_task.done():
            self._run_task.cancel()
            try:
                await self._run_task
            except (asyncio.CancelledError, Exception):
                pass
        self._run_task = None

    async def reset(self) -> None:
        """Stop runner, remove completed tasks, delete state file."""
        await self.cancel()
        self._queue = [t for t in self._queue if self._task_status.get(t.id) != TaskStatus.COMPLETED]
        for t in self._queue:
            self._task_status[t.id] = TaskStatus.PENDING
        self._progress.delete()
        self._state = SequencerState.IDLE
        self._error = None
        self._step_message = None
        self._current_task_id = None
        self._current_task_name = None
        self._current_group_idx = None
        self._frames_done_in_group = None
        self._frames_total_in_group = None

    def update_settings(self, settings: SequencerSettings) -> None:
        self._settings = settings

    # ------------------------------------------------------------------
    # Top-level runner coroutine
    # ------------------------------------------------------------------

    async def run(self) -> None:
        async with self._run_lock:
            try:
                pending = [t for t in self._queue if self._task_status.get(t.id) == TaskStatus.PENDING]
                if not pending:
                    await self._transition(SequencerState.COMPLETED)
                    await self._event_bus.publish(SequenceCompleted(tasks_done=self._count_done()))
                    return

                await self._event_bus.publish(SequenceStarted(task_count=len(pending)))

                if self._settings.unpark_on_start:
                    await self._step_unpark()

                if self._settings.autofocus_before_start:
                    await self._step_autofocus()  # STUB

                for task in self._pending_tasks():
                    await self._execute_task(task)

                if self._settings.park_on_complete:
                    await self._step_park()

                await self._transition(SequencerState.COMPLETED)
                await self._event_bus.publish(SequenceCompleted(tasks_done=self._count_done()))

            except asyncio.CancelledError:
                await self._transition(SequencerState.CANCELLED)
                await self._event_bus.publish(SequenceCancelled())
                raise
            except SequencerPausedError:
                pass  # state already set to PAUSED; runner task ends
            except Exception as exc:
                reason = str(exc)
                await self._transition(SequencerState.FAILED, reason)
                self._error = reason
                await self._event_bus.publish(SequenceFailed(reason=reason))
            finally:
                self._running = False

    # ------------------------------------------------------------------
    # Per-task coroutine
    # ------------------------------------------------------------------

    async def _execute_task(self, task: ImagingTask) -> None:
        self._task_status[task.id] = TaskStatus.RUNNING
        self._current_task_id = task.id
        self._current_task_name = task.name
        self._current_group_idx = None
        self._frames_done_in_group = None
        self._frames_total_in_group = None

        try:
            if task.do_slew and task.target_ra is not None:
                if self._settings.stop_guide_before_slew:
                    await self._step_stop_guide()
                await self._step_slew(task)
                if task.do_plate_solve:
                    await self._step_plate_solve(task)
                if self._settings.restart_guide_after_slew:
                    await self._step_start_guide()

            for group_idx, group in enumerate(task.exposures):
                self._current_group_idx = group_idx
                self._frames_total_in_group = group.count
                frames_done = self._progress.frames_done(task.id, group_idx)
                self._frames_done_in_group = frames_done

                for frame_idx in range(frames_done, group.count):
                    await self._check_pause()            # honours pause_event
                    await self._check_meridian_flip(task)
                    await self._check_autofocus_trigger()  # STUB — always skips

                    if group.filter_name is not None:
                        await self._step_change_filter(task, group.filter_name)
                        if group.refocus:
                            await self._step_autofocus()  # STUB

                    fits_path = await self._step_expose(task, group)
                    self._progress.record_frame(task.id, group_idx)
                    self._frames_done_in_group = frame_idx + 1

                    await self._event_bus.publish(SequenceFrameCompleted(
                        task_id=task.id,
                        group_idx=group_idx,
                        frame_idx=frame_idx,
                        frames_total=group.count,
                        fits_path=fits_path,
                    ))

                    if task.dither_every and (frame_idx + 1) % task.dither_every == 0:
                        await self._step_dither()

                    if task.sub_delay_s > 0:
                        await asyncio.sleep(task.sub_delay_s)

            self._progress.mark_task_done(task.id)
            self._task_status[task.id] = TaskStatus.COMPLETED
            await self._event_bus.publish(SequenceTaskCompleted(task_id=task.id))

        except (asyncio.CancelledError, SequencerPausedError):
            self._task_status[task.id] = TaskStatus.FAILED
            raise
        except Exception as exc:
            policy = task.on_error
            if policy == "skip":
                logger.warning("sequencer.task_skipped", task_id=task.id, error=str(exc))
                self._task_status[task.id] = TaskStatus.FAILED
                await self._event_bus.publish(SequenceTaskFailed(task_id=task.id, reason=str(exc)))
            elif policy == "pause":
                self._task_status[task.id] = TaskStatus.FAILED
                await self._event_bus.publish(SequenceTaskFailed(task_id=task.id, reason=str(exc)))
                self._error = str(exc)
                await self._transition(SequencerState.PAUSED, str(exc))
                await self._event_bus.publish(SequencePaused())
                await self._resume_event.wait()
                self._resume_event.clear()
                await self._transition(SequencerState.IMAGING)
                await self._event_bus.publish(SequenceResumed())
                raise SequencerPausedError(str(exc)) from exc
            else:  # abort
                self._task_status[task.id] = TaskStatus.FAILED
                await self._event_bus.publish(SequenceTaskFailed(task_id=task.id, reason=str(exc)))
                raise

    # ------------------------------------------------------------------
    # Frame-boundary checks
    # ------------------------------------------------------------------

    async def _check_pause(self) -> None:
        if not self._pause_requested:
            return
        self._pause_requested = False
        await self._transition(SequencerState.PAUSED)
        await self._event_bus.publish(SequencePaused())
        await self._resume_event.wait()
        self._resume_event.clear()
        await self._transition(SequencerState.IMAGING)
        await self._event_bus.publish(SequenceResumed())

    async def _check_meridian_flip(self, task: ImagingTask) -> None:
        if not self._settings.meridian_flip_enabled:
            return
        mount_id = self._mount_id()
        mount_manager = self._mount_manager()
        if mount_id is None or mount_manager is None:
            return
        try:
            status = await mount_manager.get_status(mount_id)
            ha = status.hour_angle
            if ha is None or ha <= self._settings.meridian_flip_ha_threshold:
                return
        except Exception:
            return

        logger.info("sequencer.meridian_flip_needed", hour_angle=ha)
        await self._transition(SequencerState.MERIDIAN_FLIP, "Performing meridian flip")

        if self._settings.stop_guide_before_slew:
            await self._step_stop_guide()

        q = self._event_bus.subscribe()
        try:
            await mount_manager.meridian_flip(mount_id)
            await self._drain_mount_event(
                q,
                ("MountMeridianFlipCompleted",),
                error_types=("MountOperationFailed",),
                timeout=300.0,
            )
        except Exception as exc:
            logger.warning("sequencer.meridian_flip_failed", error=str(exc))
            await self._transition(SequencerState.IMAGING)
            return
        finally:
            self._event_bus.unsubscribe(q)

        if self._settings.plate_solve_after_flip:
            await self._step_plate_solve(task)

        if self._settings.refocus_after_flip:
            await self._step_autofocus()  # STUB

        if self._settings.restart_guide_after_slew:
            await self._step_start_guide()

        await self._transition(SequencerState.IMAGING)

    async def _check_autofocus_trigger(self) -> None:
        # STUB — temperature delta and time-based triggers not yet implemented
        pass

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    async def _step_unpark(self) -> None:
        await self._transition(SequencerState.UNPARKING, "Unparking mount")
        mount_id = self._mount_id()
        mm = self._mount_manager()
        if mount_id is None or mm is None:
            logger.warning("sequencer.unpark_skipped", reason="no mount connected")
            return
        try:
            await mm.unpark(mount_id)
        except Exception as exc:
            logger.warning("sequencer.unpark_failed", error=str(exc))

    async def _step_park(self) -> None:
        await self._transition(SequencerState.PARKING, "Parking mount")
        mount_id = self._mount_id()
        mm = self._mount_manager()
        if mount_id is None or mm is None:
            logger.warning("sequencer.park_skipped", reason="no mount connected")
            return
        q = self._event_bus.subscribe()
        try:
            await mm.park(mount_id)
            await self._drain_mount_event(q, ("MountParked",), timeout=120.0)
        except Exception as exc:
            logger.warning("sequencer.park_failed", error=str(exc))
        finally:
            self._event_bus.unsubscribe(q)

    async def _step_slew(self, task: ImagingTask) -> None:
        label = task.target_name or f"RA={task.target_ra:.3f} Dec={task.target_dec:.3f}"
        await self._transition(SequencerState.SLEWING, f"Slewing to {label}")
        mount_id = self._mount_id()
        mm = self._mount_manager()
        if mount_id is None or mm is None:
            logger.warning("sequencer.slew_skipped", reason="no mount connected")
            return

        from astropy.coordinates import SkyCoord
        import astropy.units as u

        coord = SkyCoord(ra=task.target_ra * u.deg, dec=task.target_dec * u.deg, frame="icrs")
        await mm.set_target(mount_id, coord, name=task.target_name, source="sequencer")
        q = self._event_bus.subscribe()
        try:
            await mm.slew(mount_id)
            await self._drain_mount_event(
                q,
                ("MountSlewCompleted",),
                error_types=("MountSlewAborted", "MountOperationFailed"),
                timeout=300.0,
            )
        finally:
            self._event_bus.unsubscribe(q)

    async def _step_plate_solve(self, task: ImagingTask) -> None:
        await self._transition(SequencerState.PLATE_SOLVING, "Plate solving")
        solve_manager = self._solve_manager()
        imager_manager = self._imager_manager()
        camera_id = self._camera_id(task)

        if solve_manager is None:
            logger.warning("sequencer.plate_solve_skipped", reason="solve_manager unavailable")
            return
        if imager_manager is None or camera_id is None:
            logger.warning("sequencer.plate_solve_skipped", reason="no camera connected")
            return

        from astrolol.imaging.models import ExposureRequest
        from plugins.platesolve.models import SolveRequest

        try:
            result = await imager_manager.expose(
                camera_id,
                ExposureRequest(duration=self._settings.plate_solve_duration_s, save=False),
            )
        except Exception as exc:
            logger.warning("sequencer.plate_solve_expose_failed", error=str(exc))
            return

        req = SolveRequest(fits_path=result.fits_path)
        if task.target_ra is not None and task.target_dec is not None:
            req = req.model_copy(update={"ra_hint": task.target_ra, "dec_hint": task.target_dec})

        job = await solve_manager.submit(req)

        # Poll until the job reaches a terminal state
        loop = asyncio.get_event_loop()
        deadline = loop.time() + 120.0
        while True:
            current = solve_manager.get(job.id)
            if current and current.status in ("completed", "failed", "cancelled"):
                job = current
                break
            if loop.time() > deadline:
                logger.warning("sequencer.plate_solve_timeout")
                return
            await asyncio.sleep(0.5)

        if job.status != "completed" or job.result is None:
            logger.warning("sequencer.plate_solve_failed", error=job.error or "unknown")
            return

        # Sync mount to the solved position
        mount_id = self._mount_id()
        mm = self._mount_manager()
        if mount_id and mm:
            from astropy.coordinates import SkyCoord
            import astropy.units as u
            coord = SkyCoord(ra=job.result.ra * u.deg, dec=job.result.dec * u.deg, frame="icrs")
            try:
                await mm.sync(mount_id, coord)
                logger.info(
                    "sequencer.plate_solved",
                    ra=job.result.ra,
                    dec=job.result.dec,
                )
            except Exception as exc:
                logger.warning("sequencer.plate_solve_sync_failed", error=str(exc))

    async def _step_start_guide(self) -> None:
        await self._transition(SequencerState.GUIDING, "Starting PHD2 guiding")
        phd2 = self._phd2_client()
        if phd2 is None:
            logger.warning("sequencer.guide_skipped", reason="phd2_client unavailable")
            return
        try:
            await phd2.guide(
                settle_pixels=1.5,
                settle_time=self._settings.guide_settle_time_s,
                settle_timeout=self._settings.guide_settle_timeout_s,
            )
        except Exception as exc:
            logger.warning("sequencer.guide_start_failed", error=str(exc))

    async def _step_stop_guide(self) -> None:
        phd2 = self._phd2_client()
        if phd2 is None:
            return
        try:
            await phd2.stop_capture()
        except Exception as exc:
            logger.warning("sequencer.guide_stop_failed", error=str(exc))

    async def _step_dither(self) -> None:
        await self._transition(SequencerState.DITHERING, "Dithering")
        phd2 = self._phd2_client()
        if phd2 is None:
            logger.warning("sequencer.dither_skipped", reason="phd2_client unavailable")
            await self._transition(SequencerState.IMAGING)
            return
        try:
            await phd2.dither(
                pixels=self._settings.dither_pixels,
                ra_only=self._settings.dither_ra_only,
                settle_pixels=1.5,
                settle_time=self._settings.guide_settle_time_s,
                settle_timeout=self._settings.guide_settle_timeout_s,
            )
        except Exception as exc:
            logger.warning("sequencer.dither_failed", error=str(exc))
        await self._transition(SequencerState.IMAGING)

    async def _step_change_filter(self, task: ImagingTask, filter_name: str) -> None:
        fw_id = self._filter_wheel_id(task)
        fw_manager = self._filter_wheel_manager()
        dm = self._device_manager()
        if fw_id is None or fw_manager is None or dm is None:
            logger.warning("sequencer.filter_skipped", reason="no filter wheel connected")
            return
        try:
            fw = dm.get_filter_wheel(fw_id)
            status = await fw.get_status()
            names = status.filter_names or []
            try:
                slot = names.index(filter_name) + 1  # 1-based
            except ValueError:
                logger.warning("sequencer.filter_not_found", filter_name=filter_name, available=names)
                return
            await fw_manager.select_filter(fw_id, slot)
        except Exception as exc:
            logger.warning("sequencer.filter_change_failed", error=str(exc))

    async def _step_expose(self, task: ImagingTask, group: FilterExposure) -> str:
        await self._transition(SequencerState.IMAGING, "Exposing")
        camera_id = self._camera_id(task)
        imager_manager = self._imager_manager()
        if camera_id is None or imager_manager is None:
            raise RuntimeError("No camera available for exposure")

        from astrolol.imaging.models import ExposureRequest

        req = ExposureRequest(
            duration=group.duration,
            gain=group.gain,
            binning=group.binning,
            save=True,
        )
        result = await imager_manager.expose(camera_id, req)
        return result.fits_path

    async def _step_autofocus(self) -> None:
        """STUB — autofocus plugin not yet available."""
        logger.info("sequencer.autofocus_stub", message="Autofocus not yet available — skipping")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _transition(self, state: SequencerState, message: str | None = None) -> None:
        self._state = state
        if message is not None:
            self._step_message = message
        if message:
            await self._event_bus.publish(
                SequenceStepChanged(state=state.value, message=message)
            )

    async def _drain_mount_event(
        self,
        q: asyncio.Queue,
        success_types: tuple[str, ...],
        error_types: tuple[str, ...] = (),
        timeout: float = 300.0,
    ) -> None:
        """Drain *q* until a matching mount event arrives.

        The caller must subscribe to the event bus BEFORE triggering the hardware
        action so that events published synchronously inside the action are captured.
        """
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for mount event")
            try:
                event = await asyncio.wait_for(q.get(), timeout=min(remaining, 5.0))
            except asyncio.TimeoutError:
                continue
            class_name = type(event).__name__
            if class_name in success_types:
                return
            if class_name in error_types:
                raise RuntimeError(f"Mount operation failed: {class_name}")

    def _pending_tasks(self) -> list[ImagingTask]:
        return [t for t in self._queue if self._task_status.get(t.id) == TaskStatus.PENDING]

    def _count_done(self) -> int:
        return sum(1 for s in self._task_status.values() if s == TaskStatus.COMPLETED)
