# astrolol — deferred work

Items designed for but not yet built. Ordered roughly by priority.

## Known bugs

- **Autofocus does not work correctly in the field** — reported from real telescope use;
  behaviour has not reproduced or been diagnosed yet (unlike the rest of this section, which
  was confirmed by reading the code). Star analysis is also disabled per-frame in the main
  imaging loop today (`imaging/imager.py::_do_expose`, the commented-out `_star_analyzer_fn`
  block — too expensive on a Raspberry Pi), so autofocus is the only consumer of
  `star_detector.py`/`algorithms.py` and hasn't been cross-checked against noisy real skies,
  varying seeing, or hot pixels the way the simulator/tests exercise it. Needs a repro log
  from an actual run (curve fit points, FWHM/star-count per step, HFR trend) before a fix can
  be scoped.
- **INDI items connected from the tree are untested on real indiserver** — the mapping
  (`indi_<kind>` + `{device_name, executable}`) matches what the wizard sends and the INDI
  adapters load the driver themselves, but only non-INDI items were verified end to end.

## EQMOD native driver — assumptions & deferred items

Phase 2 (`plugins/eqmod/`) deliberately starts narrow. Each item below is an assumption
baked into the current code/design or a feature left out; revisit when it bites.

- **Northern hemisphere only** — geometry assumes the NCP; southern hemisphere (SCP home,
  mirrored Dec axis) not supported yet.
- **Home = polar home at power-on** — raw axis counters are assumed to read 0 with
  counterweights down and the OTA pointing at the pole when the mount is powered up.
- **Axis direction signs are per-mount** — whether positive counts mean E/W (RA) and N/S
  (Dec) will be measured during hardware bring-up and stored as a setting, not guessed.
- **Pier-side policy** — when both pier sides can reach a target, pick the one with the
  longest tracking time before a flip. No user-selectable policy yet.
- **Single-point sync, no alignment model** — sync is one software offset stored in
  *axis-angle* space (latest sync wins); the controller's counters are never rewritten.
  Axis space matters: it corrects zero-point error (e.g. eyeballed polar home) identically
  on both pier sides, whereas an RA/Dec-space offset would apply the Dec correction in the
  wrong direction after a meridian flip. Does not correct polar misalignment/cone error,
  which differ per pier side; per-side offsets could be added later if that ever matters.
- **No refraction** — Alt/Az and the horizon limit are geometric.
- **Meridian limit** — enforced by the driver on the *mechanical* RA axis angle (raw counts,
  sync offset ignored): up to `meridian_limit_deg` (default 20°) past counterweight-horizontal,
  symmetric so it also guards the east side. Tracking into it stops tracking (checked every
  2 s by the coords pump), GOTOs/flips/park beyond it are refused (a plain GOTO takes the
  other pier side instead), RA nudges are refused past it and stopped 0.5° before it by a
  timer. Guide pulses are not checked individually (the pump catches them). Assumes the
  power-on home is roughly right: a badly eyeballed home shifts the limit by the same error.
- **Serial transport only** — EQMOD cable (9600) or AZ-EQ6 built-in USB (115200), with
  baud auto-detect. SynScan WiFi (same protocol over UDP :11880) not implemented.
- **EQ mode only** — AZ mode / Alt-Az mounts (shared TX/RX bus with Drop line) not
  supported.
- **Out of scope for now** — PEC/PPEC, dual encoders, EEPROM/register access,
  bootloader, extended settings.
- **To probe on real hardware** — AZ-EQ6 extended status (`:q1010000`) "original position
  indexer": may allow recovering absolute axis position after a power cycle instead of
  treating it as lost.
- **Power-cycle detection** — inferred from controller counts: on connect, counts must be
  within 0.5° of the last saved position (plus sidereal drift if it was tracking), otherwise
  the saved sync offset is discarded. Park position is kept either way.
- **Controller direction convention** — assumes the CW motion bit increases the position
  counter (as indi-eqmod does). `ra_reverse` / `dec_reverse` then calibrate which way the
  counts turn the axes; one flag per axis is enough only if that CW assumption holds.
- **Stops never use channel "3"** — Instant Stop is sent per axis (`:L1`, `:L2`) like
  indi-eqmod does. `:L3` is the suspected cause of Stop not halting a GOTO on the AZ-EQ6
  (unconfirmed: to verify on hardware). Only `:F3` (init) still uses channel 3, and that one
  works on the AZ-EQ6.
- **GOTO method** — relative `:H` increment + direction bit, no `:M` brake point sent. The
  controller decelerates on its own; verify stopping accuracy on hardware. Two passes: the
  second corrects for sky motion during the first. A GOTO always ends with tracking on.
- **Offline astronomy** — LST uses the GMST formula on UTC (UT1-UTC < 0.9s ignored) and
  Alt/Az is plain spherical trig without refraction, so nothing needs IERS downloads.
  ICRS↔JNow still uses astropy FK5 (precession only, no IERS needed).
- **RA nudge while tracking** — the nudge replaces tracking for its duration instead of being
  added to it (fine for centering). Guide pulses do blend with tracking (RA speed changed on
  the fly, axis never stopped).
- **INDI mount proxy** (`astrolol_indi_mount_proxy.py`, device "astrolol Mount Proxy") —
  loaded into astrolol's *managed* indiserver only; with an unmanaged indiserver it must be
  added by hand (`indiserver … /path/to/astrolol-indi-mount-proxy`). It does not publish
  `GUIDE_RATE` (PHD2 calibrates without it); the guide rate is the `guide_rate` connect param
  (0.1–1.0x sidereal, default 0.5). Verified against a stub/real astrolol, not yet against a
  real indiserver + PHD2.

## Near-term

- **Target persistence across restart** — store the last-set target in `profiles.json` so
  it survives a backend restart.
- **Meta-scheduler (name TBD)** — decides what to image when (altitude, twilight, meridian,
  weather, blocked sky) and drives the sequencer through `app.state.sequencer`
  (`astrolol.core.sequencer.Sequencer`: `switch_to`, `insert_next`, `wait_for_task`,
  `subscribe`, interruption history per task). Not designed yet.

## Sequencer — remaining work

Design: `SEQUENCER_SPEC.md`. Done: phase 1 (core interface, queue/runner, UI), platesolve
centering, core `Guider` protocol (PHD2 + guide simulator implement it), guiding health,
per-frame guiding stats in `frame_saved`.

- **Phase 2 — guiding and stalls**
  - Test the guiding gate / recovery / stalls against the `guide_simulator` plugin (fault
    injection: star loss, guiding stops, settle failures, disconnect).
  - Guiding gate: no new frame starts until guiding has been healthy for
    `guide_healthy_after_s`; `WAITING_FOR_GUIDING` activity.
  - Guiding recovery loop: retry `guide()` every `guide_retry_interval_s`, one re-centre after
    `recenter_after_guide_loss_min`, dither counter reset on recovery.
  - Stalls: `Stall` on status/runtime, `task_stalled` / `stall_attempt` / `task_unstalled`
    events, centering "no solution" and autofocus as stalls, `stall_timeout_min`.
  - `uncount_if_unguided_s` (retake badly unguided frames, keep the file).
  - FITS header cards `GUIDLOST` / `GUIDLOSN` via an `ImagerManager` extra-header hook.
  - Autofocus integration (at start, on filter change, after flip, temperature/time
    triggers) — needs a callable, awaitable autofocus engine API per camera/focuser.
- **Phase 3 — session journal** (JSONL per run next to the images, sessions API, time
  breakdown, UI journal tab).
- **Phase 4 — multi-camera lanes** (`RigSchedule`, fit rule, efficiency estimate and
  pre-flight checks, multi-lane editor and progress).
- **Phase 5** — named sequences, one runner per mount, MCP tool surface.
- **Open decisions**
  - Guiding on by default: with the guider disconnected pre-flight only warns and the run
    then pauses on the error — block the start instead?
  - The flip hour angle is a sequencer setting (`meridian_flip_ha_hours`) separate from the
    mount's `auto_flip_ha_hours` — merge them?
- **Test isolation** — integration tests build real apps on the default data dir: they log
  into `~/.astrolol/astrolol.log` and use `/tmp/astrolol`. Point them at a tmp data dir.
- **Guiding UI** — PHD2's page is PHD2-specific; a guider-independent guiding page (graph from
  `guiding.*` events) should come with the integrated guiding module.
- **UI** — a "slew & center" button (platesolve `POST /center`) on the Mount/Target pages.

## Profiles — deferred

- **Profile duplication** — Clone button: POST a copy with a new UUID and " (copy)" suffix.
- **Import / export** — download `profiles.json`; upload to merge or replace. Useful for
  backup and sharing equipment configs between machines.
- **Map picker for location** — Leaflet embed in the location editor so users click to set
  coordinates instead of typing them.

## Plugin system — next steps

- **Runtime enable/disable without restart** — currently requires `POST /admin/restart`.
  The main blocker is that FastAPI does not support hot-swapping routers; a sub-application
  mount pattern or a proxy middleware could work around this.

## Imaging — deferred

- **Debayer + full STF preview** — colour camera preview shows raw Bayer grid today.
- **Calibration pipeline** — flat/dark/bias acquisition and application (ccdproc). Plugin.

## Mount — deferred

- **Watchdog** — periodic `ping()` calls on each connected device; transition to ERROR state
  and surface an alert in the UI without crashing the app.
- **Pointing model** — n-point alignment corrections stored per-profile.
- **Horizon limit is core, flat, and coarse** — `MountManager` refuses GOTOs below
  `horizon_min_alt_deg` (site from the active profile; no site = no check) and runs
  `horizon_action` (stop tracking / park / nothing) once when a tracking mount sinks below
  it, re-armed 1° above. Checked by the 30 s automation loop, so allow a margin. Nudges and
  sync are not checked; no horizon profile (terrain/trees) yet.
- **Meridian flip rule is northern-hemisphere** — `mount/manager.py::meridian_flip_due`
  (also used by the sequencer and the Mount page) treats pier East as normal for HA ≥ 0 and
  West for HA < 0. Unknown pier side falls back to HA only (UI: 0 < HA ≤ 2h). Revisit with
  southern-hemisphere support.

## UI consistency audit

- **Shared connect/disconnect button pattern** — PHD2 page uses an inline variant-switching
  button while Equipment page uses a different pattern. Audit all pages (PHD2, Equipment,
  Focuser, Mount) and extract a shared `ConnectButton` component so styling is identical
  everywhere.

## Post-MVP

- **Persistence layer** — SQLAlchemy + aiosqlite + Alembic migrations. Session history,
  image metadata, autofocus run data.
- **UI: red mode** — CSS filter toggle for night vision preservation.
- **UI: mobile layout** — responsive breakpoints, bottom tab navigation on small screens.
- **UI: touch target sizes** — most action buttons use `size="sm"` (h-8, 32px), below the
  recommended 44px minimum for touch. Worst offenders: `DurationStepper` +/− buttons,
  focuser move-in/out buttons, and the CollapsibleSidebar toggle strip (h-8). Audit and
  increase tap area before declaring mobile support.
- **Caddy / systemd packaging** — deployment guide for Raspberry Pi with HTTPS and autostart.
- **Auth / security** — API keys or JWT tokens. Required before any internet exposure.
  See the Security section in README.md.
