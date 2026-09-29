# Sequencer plugin — specification (v2)

## Overview

Two-tier design:

- **Sequencer** (this spec): executes an ordered queue of imaging tasks on one mount,
  with one or more cameras ("lanes") imaging in parallel. It knows nothing about
  altitude, time windows or weather — it runs what it is given, and can be stopped,
  interrupted and resumed cleanly at any point without losing progress.
- **Scheduler / meta-sequencer** (future, separate plugin): decides *what* to run and
  *when* (altitude, twilight, meridian, weather), and drives the sequencer through its
  Python API. Not designed here, but every API in this spec is shaped for it.

The Python API is a first-class interface, not an afterthought: the scheduler, user
scripts and a future MCP server all drive the sequencer through the same
`SequencerService`. The REST API is a thin layer over it.

### Design principles

1. **Definition ≠ runtime.** What the user asked for (`ImagingTask`) is stored separately
   from what has happened (`TaskRuntime`). Editing a task never loses its progress;
   resetting progress never loses the definition.
2. **Lifecycle ≠ activity.** The runner's lifecycle (`running`, `paused`, …) is a separate
   field from what it is physically doing (`slewing`, `exposing`, …). UI controls depend
   only on the lifecycle.
3. **Interrupted is not failed.** A task stopped by the user or the scheduler keeps its
   frame counts and can be resumed later. Only real errors produce `failed`.
4. **A step that cannot run is not the same as a step that failed.** A disabled plugin
   (no PHD2) → step skipped with a warning. A step that ran and failed (solve failed,
   unknown filter name) → the task's error policy applies. Nothing fails silently.
5. **Everything is journaled.** Every step, frame, interruption and decision is written to
   a structured, per-session journal, so the night can be reconstructed afterwards.
6. **One source of mount operations.** The mount and guider are shared by all lanes, but
   only the task (slew, center, flip) and the primary lane (dither) may operate them.
   Secondary lanes never touch the mount; they adapt to the primary (see *Parallel lanes*).

---

## Architecture

```
plugins/sequencer/
├── __init__.py
├── plugin.py          # SequencerPlugin — setup/startup/shutdown, restores queue
├── api.py             # FastAPI router — thin wrapper over SequencerService
├── service.py         # SequencerServiceImpl — implements the core Sequencer protocol
├── models.py          # implementation-private models only (store records, lane state)
├── runner.py          # Runner — one asyncio task per run; lane coroutines
├── steps.py           # Step implementations (slew, center, guide, expose, dither, …)
├── rig.py             # RigSchedule — next mount-operation time, secondary-lane fit rule
├── targets.py         # TargetRef resolution (favorites, resolver, coordinates)
├── journal.py         # SessionJournal — structured JSONL night log
├── store.py           # QueueStore — atomic persistence of queue + runtime
├── events.py          # Typed EventBus events
├── settings.py        # SequencerSettings
├── ui/
│   ├── index.ts       # registers event handlers, exports StatusChip
│   ├── api.ts         # fetch helpers mirroring api.py
│   ├── SequencerPage.tsx
│   ├── TaskEditor.tsx
│   ├── TargetPicker.tsx
│   ├── JournalView.tsx
│   └── SequencerChip.tsx
└── tests/
```

### Dependencies

| Dependency | Access | Required? |
|---|---|---|
| `mount_manager`, `imager_manager`, `filter_wheel_manager`, `device_manager` | `app.state` (core) | yes |
| Optical paths (camera → mount / filter wheel / focuser) | `astrolol.equipment.optical_path` | yes |
| `solve_manager` (platesolve plugin) — incl. new `center()` | `app.state` | optional |
| Guider — `astrolol.core.guiding.Guider` (PHD2 or guide simulator plugin) | `app.state.guider` | optional |
| `autofocus_engine` (autofocus plugin) | `app.state` | optional |
| Favorites (target plugin), catalogue (object_resolver plugin) | `app.state` | optional |

Optional dependencies are looked up lazily. If one is absent, the steps that need it are
**unavailable**: the pre-flight check reports them, and at run time they are skipped with a
journal entry — never silently.

The manifest no longer hard-`requires` platesolve and phd2: a user without guiding must
still be able to run a sequence. It declares them as soft ordering hints only (if the loader
supports it; otherwise `requires=[]` and lazy lookup).

### State machine implementation

Still plain asyncio, no state-machine library:

| Need | Mechanism |
|---|---|
| Lifecycle + activity visible to UI | two `StrEnum` fields, one status snapshot event |
| Cancel / stop now | `asyncio.CancelledError` through every `await`; camera `abort()` on cancel |
| Graceful stop / pause | flags checked at frame boundaries (and at task boundaries) |
| Resume after pause | `asyncio.Event` |
| One run at a time | `Runner` holds the single `asyncio.Task`; start while running → error |
| Parallel lanes | one coroutine per lane inside a `TaskGroup` |
| Shared mount / guider | `RigSchedule` — primary-driven, secondaries yield (see below) |
| Step timeouts | `asyncio.timeout()` per step, values from settings |

---

## Data model (`astrolol/core/sequencer/models.py`)

These models are the public contract (see *Python API*), so they live in core.

### `TargetRef` — how a target is specified

Nobody types J2000 coordinates. A target is a *reference* that is resolved to
coordinates at execution time (solar-system objects move; favorites may be edited).

```python
class TargetRef(BaseModel):
    kind: Literal["favorite", "catalog", "coordinates", "current"]
    name: str                         # display name, also used for FITS OBJECT / %O

    favorite_id: str | None = None    # kind=favorite → target plugin favorite
    catalog_id: str | None = None     # kind=catalog  → object_resolver name ("M 31", "Jupiter")

    # Snapshot coordinates (ICRS degrees). Filled when the user picks the target,
    # refreshed at resolution time. Used as a fallback if the source is gone
    # (favorite deleted, resolver disabled) and as the value for kind=coordinates.
    ra: float | None = None
    dec: float | None = None
```

Resolution order at task start (`targets.py`):

| kind | Resolution |
|---|---|
| `favorite` | Look up `favorite_id` in target plugin settings; fall back to snapshot + warning |
| `catalog` | Resolve `catalog_id` via object_resolver *at the current time* (planets/comets); fall back to snapshot + warning |
| `coordinates` | Snapshot as-is (power-user / API / scheduler input) |
| `current` | No slew; use the mount's current target / pointing. `name` still labels the frames |

The resolved coordinates are recorded in the journal. The object_resolver plugin should
expose a small service on `app.state` (e.g. `app.state.object_resolver.lookup(name, when)`)
rather than the sequencer reaching into `object_resolver_catalog` + `solar_system`
directly; that refactor is part of this work.

### `ExposureGroup`

```python
class ExposureGroup(BaseModel):
    filter_name: str | None = None    # None = don't touch the filter wheel
    duration: float                   # seconds
    count: int                        # total frames wanted
    binning: int = 1
    gain: int | None = None           # None = leave driver gain unchanged
    frame_type: Literal["light", "dark", "flat", "bias"] = "light"
```

### `Lane` — one camera's exposure plan within a task

```python
class Lane(BaseModel):
    id: str                           # UUID, server-assigned
    camera_id: str | None = None      # None = the profile's main camera
    groups: list[ExposureGroup]
    order: Literal["sequential", "round_robin"] = "sequential"
        # sequential:  all of group 0, then all of group 1, …
        # round_robin: one batch from each group in turn (L R G B L R G B …)
    round_robin_batch: int = 1
    autofocus_on_filter_change: bool = False
```

The filter wheel and focuser for a lane come from the camera's optical path
(`resolve_optical_paths`), never from a guess. Two lanes cannot use the same camera.

**`task.lanes[0]` is the primary lane**; any others are secondary. There is no role field
to keep consistent. Lanes have no dither setting: dithering is a task property that
follows the primary's frames (see *Parallel lanes*).

### `ImagingTask` — the definition

```python
class ImagingTask(BaseModel):
    id: str                           # UUID, server-assigned once, stable forever
    name: str | None = None           # defaults to target.name in the UI
    target: TargetRef

    lanes: list[Lane]                 # ≥ 1; lanes[0] is the primary

    # Setup (once, before the first frame; again after a resume if pointing may be lost)
    slew: bool = True                 # ignored when target.kind == "current"
    center: bool = True               # plate-solve centering loop (platesolve plugin)
    start_guiding: bool = True
    autofocus_at_start: bool = False

    # Dither cadence, counted in PRIMARY lane frames; None = never.
    # Secondary lanes are dithered whenever the primary dithers, never on their own.
    dither_every: int | None = 1

    sub_delay_s: float = 0.0          # applies to the primary; secondaries don't wait on it
    on_error: Literal["skip", "defer", "pause", "abort"] = "pause"
```

### `TaskRuntime` — what has happened

```python
class TaskStatus(StrEnum):
    PENDING     = "pending"       # never started, or progress reset
    RUNNING     = "running"
    INTERRUPTED = "interrupted"   # the task-level "pause": stopped or switched away from by
                                  # the user or a scheduler, or deferred after a stall;
                                  # progress kept; resumable at any time (setup re-runs)
    COMPLETED   = "completed"
    FAILED      = "failed"        # hardware/config error under on_error=skip/abort;
                                  # progress kept; retryable
    SKIPPED     = "skipped"       # user or scheduler skipped it

class GroupProgress(BaseModel):
    frames_done: int = 0

class LaneRuntime(BaseModel):
    lane_id: str
    groups: list[GroupProgress]
    current_group: int | None = None
    activity: Activity | None = None      # this lane's current activity

class TaskRuntime(BaseModel):
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    lanes: list[LaneRuntime]
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None
    resolved_ra: float | None = None      # last resolved target coordinates
    resolved_dec: float | None = None
    stall: Stall | None = None            # set while the task is stalled (see Stalls)
    interruptions: list[Interruption] = []   # most recent last; capped (e.g. 50)

class Interruption(BaseModel):
    at: datetime
    kind: Literal["pause", "stop", "switch", "defer", "skip", "cancel", "crash"]
    actor: str                            # "user", "scheduler:<id>", "script", "api", "system"
    reason: str | None = None             # free text, e.g. "guiding lost 20 min"
    stall_kind: StallKind | None = None   # when the interruption was caused by a stall

class StallKind(StrEnum):
    GUIDING    = "guiding"     # guiding lost / cannot (re)start
    CENTERING  = "centering"   # plate solve fails (no stars, clouds, obstruction)
    AUTOFOCUS  = "autofocus"   # not enough stars to focus

class Stall(BaseModel):
    kind: StallKind
    since: datetime
    attempts: int
    last_error: str | None
    next_attempt_at: datetime | None

class QueueEntry(BaseModel):
    task: ImagingTask
    runtime: TaskRuntime
```

Editing rules (`PUT /queue/{id}`):

- Not allowed while the task is `running` (409).
- Changing a group's `count` keeps its `frames_done` (clamped for display if over).
- Adding/removing/reordering groups or lanes: runtime is matched by lane id and group
  position; mismatches reset that lane's progress. The UI warns before saving.

### Runner status

```python
class RunState(StrEnum):          # lifecycle — drives the UI buttons
    IDLE     = "idle"             # nothing running (queue may have resumable work)
    STARTING = "starting"         # pre-flight, unpark, global setup
    RUNNING  = "running"
    PAUSING  = "pausing"          # pause requested; waiting for a frame/task boundary
    PAUSED   = "paused"           # user pause, or error under on_error=pause
    STOPPING = "stopping"         # graceful stop requested; waiting for boundary
    # a run ends by returning to IDLE; the outcome is in last_run_outcome

class Activity(StrEnum):          # what the hardware is doing right now
    UNPARKING, SLEWING, CENTERING, STARTING_GUIDING, FOCUSING,
    CHANGING_FILTER, EXPOSING, DITHERING,
    WAITING_FOR_PRIMARY,              # secondary lane: next frame wouldn't fit before the
                                      # next mount operation (dither / flip)
    WAITING_FOR_GUIDING,              # guiding lost; new frames held until it recovers
    MERIDIAN_FLIP, PARKING, WAITING   # (sub_delay, waiting on a pause)

class RunOutcome(StrEnum):
    COMPLETED, STOPPED, CANCELLED, FAILED

class SequencerStatus(BaseModel):
    run_state: RunState
    activity: Activity | None
    message: str | None               # human-readable current action
    current_task_id: str | None
    lanes: list[LaneRuntime]          # live, for the current task
    pause_reason: str | None          # "user" or the error that caused it
    stall: Stall | None               # current task's stall, if any (see Stalls)
    last_run_outcome: RunOutcome | None
    last_error: str | None
    session_id: str | None            # current journal session
    tasks_total: int
    tasks_done: int
    eta_s: float | None               # remaining exposure + estimated overhead
```

---

## Persistence (`store.py`)

**File**: `sequencer_queue.json`, next to `profiles.json`. It holds the queue (definitions
and runtime together), so a restart loses nothing.

```json
{
  "schema_version": 2,
  "entries": [ { "task": { … }, "runtime": { … } } ]
}
```

- Written atomically (`.tmp` + `os.replace`) after every frame, every status change and
  every queue edit.
- On startup: load the file. Any task left `running` (crash or power loss) becomes
  `interrupted`. The runner starts `IDLE`; the UI shows *Resume* when resumable work exists.
- The old `sequencer_state.json` (schema 1) is ignored and deleted.
- Named sequences (save / load a queue as a template): `sequences/<name>.json` with
  definitions only, no runtime. Loading appends fresh copies with new ids.

---

## Python API — interface in core, implementation in the plugin

The **interface** lives in core; the plugin only provides an **implementation**:

```
astrolol/core/sequencer/
├── __init__.py
├── models.py      # the data contract: TargetRef, ExposureGroup, Lane, ImagingTask,
│                  # TaskRuntime, QueueEntry, SequencerStatus, PreflightReport, enums
├── events.py      # the public event types (sequencer.status, .frame_saved, …)
├── errors.py      # SequencerBusy, TaskNotFound, TaskLocked, PreflightFailed
└── service.py     # class Sequencer(Protocol) — the method list below; no logic
```

- The plugin's `SequencerServiceImpl` satisfies the `Sequencer` protocol and is registered
  as `app.state.sequencer` in `setup()`. At most one sequencer implementation may be
  enabled at a time, and startup fails loudly if two try to register.
- The models are part of the interface (the protocol's signatures use them), so they live
  in core too. Implementation details stay in the plugin: settings, store format, runner,
  `RigSchedule`, journal writer.
- Consumers — the future scheduler plugin, user scripts, an MCP server, the REST router
  itself — import only `astrolol.core.sequencer` and look up `app.state.sequencer`. They
  never import `plugins.sequencer`. A different sequencer (another plugin) can be swapped
  in without changing any consumer.
- A conformance test suite in `tests/unit/test_sequencer_protocol.py` is parameterised over
  implementations, so any alternative sequencer can be checked against the same behaviour
  (lifecycle, boundaries, interrupted vs failed, progress kept).

REST, the scheduler, scripts and MCP all go through it. All methods are async, and all
raise the typed errors from `astrolol.core.sequencer.errors`, which the REST layer maps to
status codes.

```python
class Sequencer(Protocol):
    # ── Queue ─────────────────────────────────────────────────────────────
    async def list_tasks(self) -> list[QueueEntry]
    async def get(self, task_id: str) -> QueueEntry
    async def add(self, task: ImagingTask, *, position: int | None = None) -> QueueEntry
    async def insert_next(self, task: ImagingTask) -> QueueEntry   # right after the current task
    async def update(self, task_id: str, task: ImagingTask) -> QueueEntry
    async def remove(self, task_id: str) -> None
    async def reorder(self, order: list[str]) -> None
    async def reset_progress(self, task_id: str) -> None
    async def set_status(self, task_id: str, status: Literal["pending", "skipped"]) -> None

    # ── Control ───────────────────────────────────────────────────────────
    async def preflight(self, task_ids: list[str] | None = None) -> PreflightReport
    async def start(self, *, from_task: str | None = None, only: list[str] | None = None) -> None
    async def pause(self, when: Boundary = "frame", *, actor: Actor = "api") -> None
    async def resume(self, *, actor: Actor = "api") -> None
    async def stop(self, when: Boundary = "frame", *, actor: Actor = "api",
                   reason: str | None = None) -> None           # graceful; task → interrupted
    async def skip_current(self, when: Boundary = "frame", *, actor: Actor = "api") -> None
    async def cancel(self, *, actor: Actor = "api") -> None       # = stop("now")
    async def switch_to(self, task_id: str, when: Boundary = "frame", *,
                        actor: Actor = "api", reason: str | None = None) -> None
        # Atomic: interrupt the current task at the boundary (→ interrupted, progress kept)
        # and continue the SAME run with task_id (pending or interrupted). No park, no
        # session end, no unpark. If idle, equivalent to start(only=[task_id]).

    # ── Observation ───────────────────────────────────────────────────────
    def status(self) -> SequencerStatus
    async def wait_for_task(self, task_id: str) -> TaskRuntime   # resolves on any terminal/interrupted state
    async def wait_idle(self) -> RunOutcome
    def subscribe(self) -> AsyncIterator[SequencerEvent]         # filtered EventBus view

Actor = str   # "user" | "scheduler:<id>" | "script:<name>" | "api" — recorded in the journal

Boundary = Literal["now", "frame", "task"]
    # now   — abort in-flight exposures (frames discarded, journaled), stop immediately
    # frame — finish in-flight exposures, then stop
    # task  — finish the current task, then stop
```

With `switch_to()`, `insert_next()` and `wait_for_task()`, a scheduler can **preempt**
a running task: switch to another pending task, or resume an interrupted one, in the same
run. The task left behind keeps its progress and can be resumed later. How a scheduler
learns that it *should* switch is described in *Stalls* below.

A future MCP server exposes these same methods as tools (`sequencer_add_task`,
`sequencer_start`, `sequencer_status`, …). No sequencer-specific work is needed beyond
keeping the models self-describing (field descriptions on every Pydantic field).

---

## Pre-flight (`preflight()`)

Run automatically by `start()`. It can also be called on its own (the UI shows the result
before starting).

```python
class PreflightIssue(BaseModel):
    severity: Literal["error", "warning"]
    task_id: str | None
    lane_id: str | None
    code: str       # "camera_not_connected", "filter_not_in_wheel", "no_solver", …
    message: str

class PreflightReport(BaseModel):
    ok: bool        # no errors (warnings allowed)
    issues: list[PreflightIssue]
```

Errors (the start is refused, 422):

- A lane's camera is not connected, or two lanes use the same camera.
- A lane's cameras are on different mounts from each other.
- A filter name is not among the lane's wheel slot names, or the lane uses filters but
  its optical path has no filter wheel.
- `slew` is set but the target cannot be resolved and has no snapshot coordinates.
- The task has no lanes.
- A secondary group's exposure is longer than the primary's dither interval (the sum of
  the primary frame durations between two dithers). That group could never start.

Warnings (the start is allowed, and the warning is journaled):

- `center` requested but the platesolve plugin is unavailable (falls back to slew only).
- `start_guiding` / dither requested but PHD2 is unavailable or not connected.
- Autofocus requested but the autofocus plugin is unavailable.
- The mount's auto meridian flip is enabled (the sequencer suspends it during the run; see below).
- **Secondary lane efficiency below `settings.secondary_efficiency_warn` (default 80 %).**
  This is the fraction of each dither interval the secondary spends exposing (see
  *Parallel lanes*). Example: primary 9 min dither every frame, secondary 5 min →
  one 5 min frame per interval → 56 %. The UI shows this figure in the task editor too.
- A secondary lane is planned to run longer than the primary. Its frames after the
  primary finishes are taken without dithering.

---

## Runner (`runner.py`)

### Run structure

```python
async def _run(self, tasks: list[str]) -> None:
    session = self._journal.open_session(settings=..., equipment=...)
    try:
        self._set(run_state=STARTING)
        if settings.unpark_on_start: await steps.unpark()
        with self._mount_automation_suspended():      # sequencer owns flips while running
            for task_id in tasks:
                await self._boundary("task")          # pause/stop checks at task level
                await self._run_task(task_id)
        if settings.park_on_complete: await steps.park()
        outcome = COMPLETED
    except StopRequested:  outcome = STOPPED
    except CancelledError: outcome = CANCELLED; raise
    except Exception as e: outcome = FAILED
    finally:
        self._set(run_state=IDLE, last_run_outcome=outcome)
        session.close(outcome)
```

### Task structure

```python
async def _run_task(self, entry: QueueEntry) -> None:
    rt.status = RUNNING
    try:
        coord = await targets.resolve(task.target)             # journaled
        # Setup runs before any lane starts, so nothing is exposing.
        if task.slew and coord:            await steps.stop_guiding(); await steps.slew(coord)
        if task.center and coord:          await steps.center(coord, primary_camera)
        if task.start_guiding:             await steps.start_guiding()   # waits for settle
        if task.autofocus_at_start:        await gather(steps.autofocus(l) for l in lanes)
        async with TaskGroup() as tg:
            tg.create_task(self._run_primary(task, task.lanes[0]))
            for lane in task.lanes[1:]:
                tg.create_task(self._run_secondary(task, lane))
        rt.status = COMPLETED
    except StopRequested: rt.status = INTERRUPTED; raise
    except CancelledError: rt.status = INTERRUPTED; raise
    except SkipRequested:  rt.status = SKIPPED
    except StepError as e: self._apply_error_policy(task, e)
```

### Lane loops

The primary lane drives all mount operations during imaging. It behaves exactly like a
single-camera sequence, except that before dithering it waits for any secondary frame
still in flight (which should only happen through download-time jitter; see below).

```python
async def _run_primary(self, task, lane) -> None:
    for group in self._iter_groups(lane):                 # sequential or round_robin
        await steps.change_filter(lane, group.filter_name)   # once per group/batch
        if lane.autofocus_on_filter_change and filter changed: await steps.autofocus(lane)
        while batch not done:
            await self._boundary("frame")                 # pause / stop / skip
            await self._maybe_flip()                      # flip if due (all lanes idle)
            await self._triggers(lane)                    # autofocus triggers
            await steps.expose(lane, group, object_name=task.target.name)
            record frame; store.save(); journal.frame(...)
            if dither due (task.dither_every, counted in primary frames):
                await self._rig.wait_secondaries_idle()   # normally returns at once
                await steps.dither()
            if task.sub_delay_s: await sleep(task.sub_delay_s)
    self._rig.primary_done()                              # no more dithers this task

async def _run_secondary(self, task, lane) -> None:
    for group in self._iter_groups(lane):
        await steps.change_filter(lane, group.filter_name)
        if lane.autofocus_on_filter_change and filter changed: await steps.autofocus(lane)
        while batch not done:
            await self._boundary("frame")
            await self._triggers(lane)
            # The only rule a secondary follows:
            await self._rig.wait_until_fits(group.duration)   # WAITING_FOR_PRIMARY
            await steps.expose(lane, group, object_name=task.target.name)
            record frame; store.save(); journal.frame(...)
```

### Error policy

`StepError` is raised by any step that *ran and failed*. Steps that are unavailable log
a `step_skipped` journal entry and return.

| `on_error` | Effect |
|---|---|
| `skip` | task → `failed` (progress kept); continue with the next task |
| `defer` | task → `interrupted` (progress kept, stays resumable); continue with the next pending task. Meant for scheduler-driven queues, where "come back later" is the right answer to a sky problem. |
| `pause` | task stays `running`; runner → `PAUSED` with `pause_reason` = the error. **Resume retries the failed step** within the same run (for a slew or centering failure, the setup is re-run). Stop → task `interrupted`. |
| `abort` | task → `failed`; run ends with outcome `FAILED` |

This fixes the v1 bug where resuming after an error pause ended the run.

### Pause / stop / skip

All are flags checked at the named boundary (`frame` or `task`); `now` cancels in-flight
exposures via `camera.abort()` (discarded frames are journaled, not counted).

- A pause leaves guiding running. On resume, if the pause lasted longer than
  `settings.recenter_after_pause_min` or the mount was moved in the meantime (a mount slew
  event was seen), setup (center + guide) is re-run before imaging continues.
- `stop` → task `interrupted`, run outcome `STOPPED`.
- `skip_current` → task `skipped`, and the run continues with the next task.

### Meridian flip

While a run is active, the sequencer owns the flip. The `MountManager` auto-flip is
suspended for the run's duration (a new core method `suspend_automation(mount_id)`, used as
a context manager) and restored afterwards. This avoids two components flipping at once.

- The flip deadline (HA threshold from settings) is known in advance, and is one of the
  times the fit rule checks (see *Parallel lanes*). No lane, primary included, starts an
  exposure that would end after it; lanes wait instead.
- The flip is performed by the primary lane loop at a frame boundary once the deadline has
  passed and all secondaries are idle: stop guiding → flip → center (if enabled) →
  autofocus (if `refocus_after_flip`) → start guiding. A flip counts as a dither: the
  primary's dither counter restarts from zero.
- A failed flip is a `StepError` (the error policy applies). It is never swallowed:
  imaging past the meridian on the wrong pier side can hit the pier.

### Autofocus triggers

Now wired to the autofocus plugin (`app.state.autofocus_engine`), per lane (each lane's
focuser from its optical path):

- `autofocus_at_start` (task), `autofocus_on_filter_change` (lane), `refocus_after_flip`
  (settings).
- `autofocus_on_temp_delta` / `autofocus_every_min` (settings), checked at frame boundaries.

Autofocus does not move the mount, so a lane focusing doesn't block other lanes. A
secondary's autofocus exposures follow the same fit rule as its lights. A primary autofocus
only delays the next dither, which the fit rule already allows for (see below).

---

## Centering — a platesolve plugin feature

The slew → solve → sync → re-slew loop belongs to the platesolve plugin, not the sequencer.
The Mount page ("Slew & center"), the target plugin and scripts all want it too.

```python
# plugins/platesolve — new
class CenterRequest(BaseModel):
    mount_id: str
    camera_id: str
    ra: float                       # ICRS degrees
    dec: float
    tolerance_arcsec: float = 60.0
    max_attempts: int = 5
    exposure_s: float = 5.0
    binning: int = 2
    gain: int | None = None

class CenterResult(BaseModel):
    success: bool
    attempts: list[CenterAttempt]   # solved ra/dec, error_arcsec, duration per attempt
    final_error_arcsec: float | None

# app.state.solve_manager
async def center(self, req: CenterRequest) -> CenterResult     # cancellable
# REST: POST /plugins/platesolve/center → job; events platesolve.center_*
```

The sequencer calls `solve_manager.center()`, journals the attempts, and raises
`StepError` if centering does not succeed within `max_attempts`. `CenterResult` must
distinguish **no solution** (sky problem → the sequencer treats it as a centering stall)
from **solved but did not converge** (a pointing problem → error).

---

## Parallel lanes (multi-camera)

### Why lanes instead of parallel tasks

Two cameras on the same mount always point at the same place. Two independent tasks with
different targets cannot really run in parallel on one mount — one of them would have to
own the pointing. So the unit of parallelism is the **lane**: one task (one target, one
pointing) with N cameras, each with its own exposure plan, filter wheel and focuser.

- **One queue per mount.** Multiple mounts means multiple fully independent runners, with
  nothing shared. v1 implements a single runner bound to the profile's mount, but every
  model and route is keyed so that `runner_id = mount_id` can be added later without
  breaking changes.
- Lane-local resources (camera, filter wheel, focuser, rotator) belong to their lane alone,
  so they need no coordination. Filter changes, focusing and downloads run fully in
  parallel.
- Rig resources (mount pointing, guider) are shared by every lane of the task, but only one
  lane may operate them: the **primary** (`lanes[0]`).

### The primary drives, secondaries follow

**The task follows the primary lane.** The primary lane images exactly as if it were
alone: it dithers every `task.dither_every` of its own frames and performs the meridian
flip. Secondary lanes **never** operate the mount. They are dithered whenever the primary
dithers, and they fit their exposures into the gaps between the primary's mount operations.

| Operation | Who may do it | When |
|---|---|---|
| Slew, center, start guiding | task setup | before any lane starts |
| Dither | primary lane only | after every `dither_every` primary frames |
| Meridian flip | primary lane loop | at the first primary frame boundary past the deadline |
| Exposure, filter change, autofocus | every lane | any time (secondaries: subject to the fit rule) |

Because mount operations have a single source, they are strictly sequential. Two lanes
cannot issue conflicting commands (e.g. a dither and a flip), so no lock or arbitration is
needed.

### The fit rule (the only rule a secondary follows)

The `RigSchedule` keeps **T_next**, the earliest time the next mount operation can happen:

```
T_next = min(
    end of the primary's current exposure
      + durations of the primary frames still to take before the next dither,
    meridian flip deadline,
)
```

(If the primary isn't exposing, the first term counts from *now*. If the primary has
finished its plan, this term is dropped.)

A secondary starts an exposure only if `now + duration + download_margin ≤ T_next`.
Otherwise it waits (`WAITING_FOR_PRIMARY`) until the mount operation is done and T_next has
moved forward.

- **T_next is a lower bound.** The primary can be late (filter change, autofocus, a slow
  download) but never early. So a secondary that passed the check never overlaps a dither.
  The primary never waits for secondaries except when a download overruns
  `settings.download_margin_s`. It then waits for that frame, and the journal records a
  `rig_wait`.
- **Secondaries never slow down the primary; the primary's timing decides the secondaries'
  efficiency.** Users must plan secondary exposures around the primary:

  | Primary | Secondary | Result per dither interval | Secondary efficiency |
  |---|---|---|---|
  | 10 min, dither every frame | 2 min | 5 frames, no idle | 100 % |
  | 10 min, dither every frame | 3 min | 3 frames, 1 min idle | 90 % |
  | 9 min, dither every frame | 2 × 5 min wanted | 1 frame; the 2nd **always** waits for the dither | 56 % |
  | 5 min, dither every 3 frames | 5 min | 3 frames, no idle | 100 % |
  | 10 min, no dithering | anything | only the flip interrupts | ≈ 100 % |

  In the third row, the second 5-minute exposure can never be started before the dither.
  It waits every time, and the secondary loses 4 minutes out of every 9. The task editor
  shows this efficiency per secondary lane, and pre-flight warns below
  `settings.secondary_efficiency_warn`. Pre-flight refuses a secondary exposure that is
  longer than a full dither interval, because it could never start.
- **Secondary lanes can't have their own dither cadence.** If a secondary needs more
  frequent dithering, it should be the primary, or the primary should dither more often.
- **Once the primary has finished its plan,** there are no more dithers. Secondaries still
  running go on undithered (pre-flight warns about this). The primary lane keeps owning the
  mount meanwhile: it still flips at the flip point and restarts guiding if it drops. The
  task completes when every lane has finished.
- **Estimate** (pre-flight, task editor): a secondary fits
  `floor((interval − duration − margin) / duration) + 1` frames per dither interval (the
  allowance is charged once per start decision; real download time is not modelled, so
  real runs usually do a little better).
- **Autofocus on a secondary lane** marks the lane busy: the primary waits for it before its
  next dither (the one case where the primary waits for a secondary). Autofocus runs one at
  a time across lanes (the autofocus engine runs one run at a time).
- **Boundaries:** at a frame boundary with a pause/stop/skip/switch pending, each lane stops
  on its own once its current frame is done (a lane never aborts another lane's exposure);
  the request takes effect when every lane has stopped. "Now" aborts every lane's
  exposure. An *error* in one lane stops the others (their in-flight frames are discarded)
  and goes through the task's error policy.

### Guiding loss

The guider is shared, so its health applies to every lane. On a cloudy night guiding is
lost all the time: often for a few seconds, and sometimes for an hour. The design follows
three principles.

**1. In-flight exposures are never interrupted.** A frame that loses guiding at 9:30 of a
10-minute exposure is completed and saved. Whether it is usable is decided at processing
time. The journal and FITS header record exactly how much of the exposure was unguided,
so the frame can be judged (or filtered automatically) later.

- Every saved frame records `unguided_s` (total seconds without a valid guide step during
  the exposure) and `guiding_loss_events` (count). These are also written into the FITS header
  (`GUIDLOST`, `GUIDLOSN`) through the `ImagerManager` extra-header hook.
- Frames are **always kept on disk**. They count towards the plan unless
  `settings.uncount_if_unguided_s` is set and exceeded (default `None`: always counted).
  With a threshold, the plan retakes the frame, but the original stays on disk for the
  user to judge.

**2. New exposures only start while guiding is healthy.** The gate checked at every frame
boundary (every lane, before the fit rule) is: guiding is active, and there has been at least
`settings.guide_healthy_after_s` (default 10 s) of continuous valid guide steps since the
last loss. While unhealthy, lanes wait (`WAITING_FOR_GUIDING`). A short loss in the middle of
an exposure therefore costs nothing. A short loss right at a frame boundary costs a few
seconds of waiting.

The runner watches the PHD2 client's state:

| PHD2 state | Meaning | Sequencer reaction |
|---|---|---|
| `Guiding` | healthy (after the hysteresis) | frames may start |
| `Star loss` | PHD2 still trying; star not found in the last frames | hold new frames; nothing else |
| `Stopped` / `Looping` / disconnected | PHD2 gave up (or crashed) | hold new frames and start the **recovery loop** |

**3. Recovery retries regularly and waits patiently.** It doesn't give up after N attempts.

```
recovery loop (runs in the primary lane loop, which owns guider operations):
    lost_since = now
    every settings.guide_retry_interval_s (default 60 s):
        if now − lost_since > settings.recenter_after_guide_loss_min (default 15 min)
           and not yet re-centred since the loss:
            try center()                  # clouds: solve fails → just another failed attempt
        try guide() + wait for settle     # SettleDone ok → recovered; exit loop
        journal a guiding_retry record (attempt n, result)
        update the task's Stall (kind=guiding); apply the stall timeout (see Stalls)
```

- The recovery loop is one case of a **stall** (next section): it is reported to any
  scheduler as it happens, and a scheduler can switch away at any time. Without a
  scheduler, and with no timeout (the default), it retries until dawn or until the user
  stops it.
- **The meridian flip still happens during an outage.** The flip deadline doesn't wait for
  the clouds. The flip itself doesn't need guiding; the recovery loop then continues from
  the new pier side.
- **Dithers due during an outage are dropped.** A successful recovery restarts guiding on
  a freshly selected star, which counts as a dither; the primary's dither counter resets.
- `stop`, `pause` and `skip` stay responsive during recovery: the loop's waits are
  ordinary `await`s, and boundary checks happen between attempts.

Per-frame guiding RMS (from PHD2 guide steps during the exposure, excluding lost periods)
is recorded in the journal for every frame of every lane.

### Stalls: sky problems, and handing the decision to a scheduler

Some failures are about the **sky**, not the hardware: guiding can't find a star, plate
solving finds no stars, autofocus has too few stars. They usually mean clouds, or that this
part of the sky is blocked (a tree, a building, the dome). Retrying later, or going to a
different part of the sky, may well succeed. The sequencer treats these as **stalls**, not
errors:

| Failure | Classification | Handling |
|---|---|---|
| Guiding lost / can't start or settle | stall `guiding` | retry every `guide_retry_interval_s` |
| Plate solve fails during centering (no solution, too few stars) | stall `centering` | retry every `center_retry_interval_s` |
| Centering solves but can't converge within tolerance | **error** | → `on_error` (pointing/mechanics problem, not sky) |
| Autofocus: not enough stars / bad curve | stall `autofocus` | retry every `autofocus_retry_interval_s`; lanes keep the last good focus meanwhile |
| Slew fails, camera error, filter error, PHD2 not connected at all | **error** | → `on_error` |

While a stall lasts:

1. **It's visible.** `SequencerStatus.stall` and `TaskRuntime.stall` hold the kind, the
   start time, the attempt count, the last error and the next attempt time. Events
   `sequencer.task_stalled` (once, at the first failed attempt),
   `sequencer.stall_attempt` (each retry) and `sequencer.task_unstalled` (on recovery,
   with the duration) are published and journaled.
2. **Retries go on by themselves.** Nothing needs to be driven from outside; the
   sequencer is fully usable without any scheduler.
3. **Any actor can take over.** A scheduler subscribed to the events can call
   `switch_to(other_task, when="frame", actor="scheduler:…", reason="guiding stalled 20 min")`
   at any moment: new frames are already on hold, so "frame" takes effect immediately
   unless a frame is still being exposed. The stalled task becomes `interrupted` with an
   `Interruption` record (`kind=switch`, `stall_kind=guiding`) that the scheduler can read
   back later when deciding whether to retry that part of the sky.
4. **A timeout is the fallback when nobody decides.** `settings.stall_timeout_min` (default
   `None` = retry forever) turns a stall that lasts too long into a `StepError` with that
   `stall_kind`. It is then handled by the task's `on_error`; for scheduler-driven queues,
   `defer` is the natural choice (the task is set aside as `interrupted`, and the run moves
   to the next pending task).

**Resuming a task after an interruption** always re-runs setup (slew → center → guide),
since the mount has pointed elsewhere in the meantime. Frames already taken are kept,
and the lanes continue from their saved progress.

The sequencer never decides *where else to go*. It keeps no notion of blocked sky
regions, altitude or priority; that is the scheduler's job. It supplies the facts
(stall kind, duration, attempts, interruption history per task) and the controls
(`switch_to`, `insert_next`, `stop`, `defer`).

### What the primary lane is for

- Its frames set the dither cadence and the pace of the whole task.
- Its camera is used for centering (a plate solve needs the main optical path; a
  `solve_camera_id` override on the task can be added later if needed).
- Its target name / filter is used in status summaries.

---

## Session journal (`journal.py`)

The standard log (`astrolol.log`) is for debugging. The journal records *what happened
tonight*, in a structured form, for the user.

### Storage

- One session = one run (`start()` → back to `IDLE`). Stored as JSONL at
  `<journal dir>/<YYYY-MM-DD>_<HHMM>_<session-id>.jsonl`. The journal dir defaults to
  `journal` in the fixed part of the image save template (`~/astrolol_pictures/%D` →
  `~/astrolol_pictures/journal`); the `journal_dir` setting overrides it.
- Append-only, one record per line, flushed per record (survives a crash).
- The journal is the persisted form of the sequencer's EventBus events: the same Pydantic
  models, one serialisation. Anything a WebSocket client sees live can be replayed from
  the journal.

### Record types (all have `ts`, `session_id`, `task_id?`, `lane_id?`)

| Record | Content |
|---|---|
| `session_started` | settings snapshot, profile, equipment (optical paths), queue snapshot |
| `task_started` / `task_finished` | status, frame totals per lane/group, duration |
| `target_resolved` | kind, source, name, ra/dec, fallback used? |
| `step_started` / `step_finished` | step kind, duration, result details (see below) |
| `step_skipped` | step kind, reason (plugin unavailable, …) |
| `step_failed` | step kind, error, policy applied |
| `frame_saved` | path, filter, duration, gain, binning, sensor temp, focuser position, HA/alt at mid-exposure, guide RMS (RA/Dec/total), `unguided_s`, `guiding_loss_events`, counted? |
| `frame_discarded` | reason (stop now, …) — aborted exposures only; saved frames are never discarded |
| `rig_wait` | lane, what it waited for (`dither`, `flip`, `primary_download`), duration |
| `interruption` | kind (pause, stop, switch, defer, skip, cancel), actor, reason, boundary, stall kind if any |
| `stall` | task_stalled / stall_attempt / task_unstalled: kind, attempt n, error, duration |
| `resumed` | after how long; whether setup was re-run |
| `guiding_event` | star lost / recovered (with duration), guiding stopped, retry attempt n + result, re-centre during outage, settle done/failed |
| `session_finished` | outcome, integration totals per target/filter/lane |

Step details: slew (from/to, duration); center (each attempt: solved coords, error in
arcsec); dither (pixels, settle time, settled?); flip (pier side before/after, duration);
autofocus (curve summary, best position, HFR, temperature).

### API and UI

```
GET /plugins/sequencer/sessions                → list[SessionSummary]
GET /plugins/sequencer/sessions/{id}           → list[JournalRecord]
GET /plugins/sequencer/sessions/{id}/summary   → SessionSummary (totals, time breakdown)
GET /plugins/sequencer/sessions/{id}/export?format=csv|md
```

- **Time breakdown:** for the whole session, how much time went to exposing, slewing,
  centering, dithering/settling, flip, focus, waiting for the rig, and paused. This answers
  "where did my night go?".
- **UI Journal tab:** a timeline per lane (Gantt-like: exposures as bars, dithers and
  flips as markers across all lanes), with a table of frames below it (sortable,
  flags highlighted), and a totals summary.

---

## Events (`events.py`)

Typed `BaseEvent` subclasses (TS types in `ui/src/api/types.ts`). The main event is a
full status snapshot, so the UI and the scheduler never have to piece state together
from deltas:

```python
class SequencerStatusChanged(BaseEvent):      # emitted on EVERY status change
    type: Literal["sequencer.status"] = "sequencer.status"
    status: SequencerStatus

class SequencerQueueChanged(BaseEvent):       # any queue/runtime change
    type: Literal["sequencer.queue_changed"] = "sequencer.queue_changed"
    entries: list[QueueEntry]
```

Plus the fine-grained events, which are the same objects the journal writes:
`sequencer.session_started`, `.task_started`, `.task_finished`, `.step_started`,
`.step_finished`, `.step_skipped`, `.step_failed`, `.frame_saved`, `.frame_discarded`,
`.interruption`, `.resumed`, `.rig_wait`, `.task_stalled`, `.stall_attempt`,
`.task_unstalled`, `.session_finished`. Every control action carries its `actor`, so the
journal shows who (user, scheduler, script) did what, and why.

---

## REST API (`api.py`)

All routes are under `/plugins/sequencer/`, and each one is a one-line call to `SequencerService`.

```
# Queue
GET    /queue                         → list[QueueEntry]
POST   /queue?position=N              body: ImagingTask (id ignored) → QueueEntry (201)
POST   /queue/insert_next             body: ImagingTask → QueueEntry (201)
GET    /queue/{id}                    → QueueEntry
PUT    /queue/{id}                    body: ImagingTask → QueueEntry   (409 if running)
DELETE /queue/{id}                    → 204                            (409 if running)
POST   /queue/{id}/duplicate          → QueueEntry (201)
POST   /queue/{id}/reset_progress     → QueueEntry                     (409 if running)
POST   /queue/{id}/skip               → QueueEntry  (pending → skipped; running → skip_current)
POST   /queue/{id}/unskip             → QueueEntry
POST   /queue/reorder                 body: {order: [ids]} → 204
DELETE /queue?status=completed|skipped|all_not_running → 204

# Named sequences
GET    /sequences                     → list[str]
POST   /sequences/{name}              → save current queue definitions
POST   /sequences/{name}/load         → append to queue

# Control
POST   /preflight                     body: {task_ids?} → PreflightReport
POST   /start                         body: {from_task?, only?} → 202 | 409 busy | 422 preflight
POST   /pause?when=frame|task|now     → 204
POST   /resume                        → 204
POST   /stop?when=frame|task|now      → 204
POST   /skip_current?when=frame|now   → 204
POST   /switch                        body: {task_id, when?, reason?} → 204

# Status, settings, journal
GET    /status                        → SequencerStatus
GET    /settings  /  PUT /settings    → SequencerSettings
GET    /sessions …                    (see Journal)
```

`POST /reset` from v1 is gone. It mixed "cancel", "clear completed" and "reset progress";
each of those is now a separate, explicit operation.

---

## Settings (`settings.py`)

```python
class SequencerSettings(BaseModel):
    # Mount lifecycle
    unpark_on_start: bool = True
    park_on_complete: bool = False

    # Guiding
    guide_settle_pixels: float = 1.5
    guide_settle_time_s: int = 10
    guide_settle_timeout_s: int = 60
    guide_healthy_after_s: float = 10.0          # continuous guiding before new frames start
    guide_retry_interval_s: float = 60.0         # recovery loop cadence
    recenter_after_guide_loss_min: float = 15.0  # re-centre once during a long outage
    center_retry_interval_s: float = 120.0       # centering stall retry cadence
    autofocus_retry_interval_s: float = 300.0    # autofocus stall retry cadence
    stall_timeout_min: float | None = None       # any stall; None = retry until stopped
    uncount_if_unguided_s: float | None = None   # None = unguided frames still count

    # Dither
    dither_pixels: float = 3.0
    dither_ra_only: bool = False

    # Multi-lane
    download_margin_s: float = 10.0            # added to a secondary exposure in the fit rule
    secondary_efficiency_warn: float = 0.8     # pre-flight warning threshold

    # Meridian flip (sequencer-owned while running)
    meridian_flip_enabled: bool = True
    meridian_flip_ha_hours: float = 0.1
    center_after_flip: bool = True
    refocus_after_flip: bool = False

    # Centering (passed through to platesolve center())
    center_tolerance_arcsec: float = 60.0
    center_max_attempts: int = 5
    center_exposure_s: float = 5.0
    center_binning: int = 2

    # Autofocus triggers
    autofocus_on_temp_delta: float | None = None   # °C
    autofocus_every_min: float | None = None

    # Resume behaviour
    recenter_after_pause_min: float = 10.0

    # Step timeouts
    slew_timeout_s: float = 300.0
    flip_timeout_s: float = 300.0
    exposure_timeout_margin_s: float = 120.0       # on top of the exposure duration
```

---

## UI

### Page layout

```
┌─ Control bar ──────────────────────────────────────────────────────────┐
│ [● RUNNING] Exposing Ha 12/30 · M 42                  ETA 3h12 · 4/7   │
│ ▓▓▓▓▓▓▓▓░░░░ frame   ▓▓▓▓░░░░░░ task   ▓▓░░░░░░░░ queue               │
│ [Pause ▾] [Stop ▾] [Skip task]                    (▾ = frame/task/now) │
│ ⚠ paused: plate solve failed (3 attempts, 4.2′ off)   [Retry] [Skip]  │
└────────────────────────────────────────────────────────────────────────┘
 Tabs:  Queue | Journal | Settings

 Queue tab
 ┌ ⋮⋮ M 42  ● running ──────────────────────────────── [⋯] ┐
 │   Main (ASI2600MM)  L 20/40 ▓▓▓▓░  R 0/10  G 0/10  B 0/10│
 │   Wide (ASI585MC)   — 45/120 ▓▓░░░  follows main · 90 %  │
 ├ ⋮⋮ NGC 7000  ◐ interrupted  Ha 12/30 ────────────── [⋯] ┤
 ├ ⋮⋮ Jupiter   ○ pending ─────────────────────────── [⋯] ┤
 └ [+ Add task]   [Load sequence ▾] [Save as…] [Clear done]  ┘
```

- **Control buttons** depend only on `run_state`:
  - `IDLE`: *Start*, or *Resume* when interrupted work exists. A *Start from…* option
    is available in each task's menu.
  - `RUNNING`: *Pause ▾* and *Stop ▾* (after frame / after task / now), *Skip task*.
  - `PAUSING` / `STOPPING`: a disabled button showing "Pausing after frame…", plus
    *Now* to escalate.
  - `PAUSED`: *Resume*, *Stop*, and the error banner with *Retry* / *Skip* when it was
    paused by an error.
- **Task menu `[⋯]`:** Edit, Duplicate, Start from here, Reset progress, Skip/Unskip,
  Delete.
- **Task cards:** drag to reorder, and expand to show each lane with a progress bar per
  group.
- **Pre-flight:** issues are shown inline on the affected task or lane before starting.
  *Start* stays enabled with warnings and is disabled with errors.

### Task editor (drawer)

1. **Target** (`TargetPicker`):
   - Search box backed by object_resolver `/search` (catalogue, solar system, SIMBAD fallback).
     It shows type, magnitude, and tonight's altitude and imaging window from the target
     plugin's `/ephemeris`.
   - A **Favorites** list from the target plugin (one click).
   - **"Current mount target"** (`kind=current`).
   - Coordinates are shown read-only for the choice; manual RA/Dec entry is hidden
     behind an "Advanced" toggle.
2. **Cameras / lanes:** one lane per connected camera, from the active profile's optical
   paths; toggle each on or off. The first lane is the primary (drag to change it). The
   editor states plainly that **the task follows the primary lane**: secondaries only fit
   exposures between the primary's dithers. It shows each secondary's estimated efficiency,
   with a hint when it is poor (e.g. "5 min subs fit once per 9 min dither interval —
   56 %. Try 4 min, or 3 × 3 min").
3. **Exposure groups per lane:** an editable table. The filter dropdown lists the lane's
   wheel slot names. Columns: duration, count, gain, binning, and per-row integration time.
   Add/remove/reorder rows; *sequential* vs *round-robin*.
4. **Setup and behaviour:** slew, center, start guiding, autofocus at start, dither every N,
   sub delay, and error policy — with the defaults collapsed under "Options".

### Wiring

- Types go in `ui/src/api/types.ts`; fetch helpers in `plugins/sequencer/ui/api.ts`.
- `registerPluginEventHandlers('sequencer', {'sequencer.status': …, 'sequencer.queue_changed': …})`:
  the page reads `pluginStates['sequencer']`, and fetches once on mount. No polling.
- `SequencerChip` shows the run state, the current target, and frame n/N; it pulses while
  exposing.
- An `EventLog` filtered to `sequencer` sits under the queue for debug output.

---

## Core / other-plugin changes required

| Where | Change |
|---|---|
| `platesolve` | `SolveManager.center()` + `POST /plugins/platesolve/center` + events |
| `object_resolver` | Service object on `app.state` (`lookup(name, when)`, `search(q)`) instead of route-only logic |
| `target` | Service accessor for favorites on `app.state` |
| `MountManager` | `suspend_automation(mount_id)` context manager (pauses auto-flip; horizon checks stay active) |
| `ImagerManager` / `ExposureRequest` | Optional `object_name` override, so frames are named after the task target even without a slew. `abort` on cancellation verified. |
| `astrolol/core/guiding/` | Done: `Guider` protocol (`app.state.guider`, one active guider) with settle-waiting `guide()`/`dither()`, guiding health and per-window stats (RMS, unguided seconds, losses). Implemented by the PHD2 plugin and the `guide_simulator` plugin (fault injection for tests) |
| `ImagerManager` | Done: `add_fits_header_cards()` — the sequencer writes `GUIDLOST`, `GUIDLOSN`, `GUIDRMS` after each frame |
| `astrolol/core/sequencer/` | New: the `Sequencer` protocol, public models, events and errors (interface only) |
| `autofocus` | Done: `engine.focus(camera_id, focuser_id)` — awaitable, cancellable, uses the plugin's saved settings; a failed or aborted run restores the focuser; `sky_problem` marks no-star failures |

---

## Testing

Per the project rules, every feature gets tests. At minimum:

- **Queue / store:** CRUD, reorder, insert_next, duplicate; persistence across a simulated
  restart (a running task becomes interrupted); edit keeps progress; reset progress.
- **Lifecycle:**
  - start → complete;
  - pause at frame and at task boundaries → resume;
  - stop at frame / task / now (task interrupted, progress kept; "now" discards the
    in-flight frame);
  - skip;
  - a second concurrent start is rejected;
  - `switch_to` mid-task: same run and session, no park/unpark, left task `interrupted`
    with an `Interruption` record carrying the actor and reason; switching back resumes from
    saved progress and re-runs setup.
- **Stalls:** each kind is classified correctly (no solution → stall; not converged →
  error); status and events during a stall; `switch_to` during a stall takes effect
  without waiting for the next retry; `stall_timeout_min` → `StepError` → `defer` moves on
  and leaves the task resumable.
- **Error policy:** `skip` / `pause` (resume retries the step and the run continues) /
  `abort`; a step that is unavailable vs one that failed.
- **Pre-flight:** each error and warning code.
- **Targets:** each `kind`; fallback to the snapshot when the favorite is deleted or the
  resolver is disabled.
- **RigSchedule (unit-tested in isolation, fake clock):** T_next computation across group
  changes, `dither_every > 1`, the primary not exposing, the primary finished, and the flip
  deadline; the fit decision; efficiency estimate (the table in *Parallel lanes* as test
  cases).
- **Lanes:**
  - two fake cameras with different durations: exactly one dither per primary cadence; no
    secondary exposure overlaps a dither or flip; the primary never waits (except when a
    download overruns, which is journaled as `rig_wait`);
  - the 9 min / 2 × 5 min case: the second secondary frame always waits for the dither;
  - the primary finishes first: secondaries continue undithered, and the task completes
    when all lanes are done;
  - a flip during a multi-lane run.
- **Guiding loss (fake PHD2 client, fake clock):**
  - a short loss mid-exposure: the frame completes, `unguided_s` is recorded, and no lane
    waits afterwards;
  - a loss at a boundary: every lane holds until `guide_healthy_after_s` of guiding;
  - PHD2 stops: retries at the configured interval, re-centres once after the threshold,
    recovers, and the dither counter resets;
  - a timeout set → `StepError` → error policy; no timeout → still retrying after hours;
  - stop, pause and skip during recovery;
  - a flip during an outage;
  - `uncount_if_unguided_s` retakes the frame and keeps the file.
- **Journal:** the record sequence for a small run; a crash mid-run leaves a readable file;
  the summary time breakdown adds up to the session duration.
- **Python API:** `wait_for_task`, `wait_idle`, and a preemption flow (stop → insert_next → start).

---

## Implementation phases

1. **Single-lane core redo:**
   - `astrolol/core/sequencer/` interface (protocol, models, events, errors) and the
     protocol conformance tests;
   - models (definition/runtime split, TargetRef, lanes with one lane only);
   - store, service, runner with the new lifecycle and error policy, pre-flight;
   - REST, events, and the new UI (target picker, group table, controls).
   - This fixes every v1 bug.
2. **Platesolve centering, PHD2 settle-await and guiding-health API.** Guiding-loss handling
   (gate, recovery loop, per-frame unguided time), autofocus triggers, and the
   sequencer-owned meridian flip.
3. **Session journal:** records, storage, API, UI journal tab.
4. **Parallel lanes:** RigSchedule and the fit rule, secondary lane loop, efficiency estimate and pre-flight checks, multi-lane editor and progress UI.
5. **(Later)** Named sequences, multiple mounts (runner per mount), MCP tool surface.

## Known v1 defects this spec replaces

For traceability — all of these are addressed by the design above:

- Progress persistence could never match, because POST regenerated ids and the queue
  was in memory only.
- `on_error=pause` ended the run on resume and left the state stuck on `imaging`.
- `pause?mode=after_task` was ignored.
- `GET /queue` returned tasks without status; the UI expected `{task, status}`.
- Cancel marked the task `failed`.
- Most step failures (slew, solve, filter, guide, flip) were swallowed, and imaging continued.
- The filter was changed before every frame.
- `guide()` didn't wait for settle.
- Plate solving synced but never re-centered.
- The meridian flip was duplicated with the MountManager auto-flip.
- Autofocus was stubbed although the plugin exists.
- The UI had no RA/Dec input (slewing was impossible), used a single group, had no filter,
  edit or reorder, and polled instead of using events.
