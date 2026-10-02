# astrolol — deferred work

Items designed for but not yet built. Ordered roughly by priority.

## Known bugs

- **INDI items connected from the tree are untested on real indiserver** — the mapping
  (`indi_<kind>` + `{device_name, executable}`) matches what the wizard sends and the INDI
  adapters load the driver themselves, but only non-INDI items were verified end to end.
- **Hot-enabling a plugin is unreachable once `ui/dist` exists (production mode)** — the
  SPA catch-all route (`astrolol/api/static.py::spa_fallback`, registered once at startup
  in `mount_ui()`) sits earlier in Starlette's route list than a router added later via
  `POST /settings`'s hot-enable path (`astrolol/app.py`, the `PluginManifest.hot_reloadable`
  mechanism from commit 000396f). Starlette matches routes in registration order, not
  specificity, so every request under that plugin's `/plugins/<id>/...` prefix hits the
  catch-all first and gets a 404, even though the route legitimately exists (shows up in
  `/openapi.json`). Confirmed live: hot-enabling `viewer` on a running production-mode
  instance 404'd every one of its endpoints; a full restart (which sets it up before
  `mount_ui()` runs, in the normal `setup_plugins()` order) fixed it immediately. Affects
  *any* hot-reloadable plugin enabled after boot while serving the built UI — dev mode
  (Vite dev server, no `mount_ui()` call) is unaffected. Fix is presumably to either
  register hot-enabled routers ahead of the catch-all (e.g. `app.router.routes.insert()`
  before the `spa_fallback` route) or move the API-prefix 404 check earlier so it doesn't
  depend on route order at all.

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

## From the 2026-10-01 night session

Observations from a real imaging session (IC 1795, Ha/L/R/G/B) logged in `oct_1/`.
Trivial items from that session (mobile sidebar scroll, EFW filter-name comma input,
`indi.message` log spam, stale filter cache on sequencer resume, missing FITS `FILTER`
header, `EventBusForwarder` forwarding debug logs to the UI regardless of the logger's
actual level, favorites silently failing to save because `crypto.randomUUID()` throws
over plain HTTP by hostname) were fixed in the same session — see git log. The rest needs
more design/testing than a single sitting allows:

- **Polar-align wizard's first point can land near the pole** — the 3-point fit picks its
  own RA/Dec test points and on 2026-10-01 the first one landed close to DEC=90°, which
  the mount struggled with (confirmed in `astrolol.log`: `mount.target_set` with
  `dec≈89.85`). It went fine after the user manually picked a lower Dec. Either let the
  user pick/override the starting Dec, or bias the wizard's point selection away from the
  pole by default.
- **Polar-align "Refresh" can get stuck repeating a stale fit** — after a 3-point fit, the
  user hit Refresh and kept getting the same "5.6′ too high / 8.1′ east" result
  (`polar_align.fit_completed` not re-running the solve, or re-solving against a cached
  frame — needs to be reproduced and root-caused). Wanted: a start/stop auto-refresh with
  a configurable interval instead of a manual one-shot button.
- **Autofocus star detector picks up hot pixels, especially on defocused frames** — no
  single run worked reliably with the L filter that night (`autofocus.failed`: "Focus
  curve did not fit a valid V shape" × 6 in `astrolol.log`). `plugins/autofocus/star_detector.py`
  needs a hot-pixel rejection pass (e.g. a bad-pixel map, or rejecting single-pixel-wide
  sources) before HFD/FWHM measurement.
- **FWHM metric performs much worse than HFD** for autofocus on this rig — consider
  defaulting new autofocus configs to HFD, or investigating why FWHM's star fit is so much
  more hot-pixel-sensitive than HFD's.
- **Parallel-lane "too long" warning fires on two identical-duration lanes** — in
  `plugins/sequencer/lanes.py::estimate_lanes`, when a secondary lane's exposure duration
  equals (or is close to) the primary's and `dither_every` is tight, `room = interval -
  duration - margin_s` goes negative even though the two lanes are nominally the same
  length, so `per_interval` floors to 0 and `wall_s` blows up to `inf` / triggers
  `secondary_outlasts_primary` — observed with two 300×10 lanes. The "fits between
  dithers" model may need a special case (or a clearer message) for lanes whose group
  durations match the primary's.
- **OOM browsing images in the viewer** — expensive per-image operations (thumbnailing,
  full-res preview, star detection for quality scoring) should be serialized behind the
  memory-pressure-aware mutex mentioned in the architecture notes (not built yet) so
  browsing a large image set on a Pi can't exhaust memory.
- **Resuming a sequencer task after a crash skips re-plate-solving** — a crash mid-task
  should be treated like a long pause on the next startup (force `setup_needed=True` so
  `_setup()`'s slew/center/plate-solve runs again), not resume straight into exposing at
  the last known pointing.
- **Too many PHD2 "star lost" notifications** — `phd2.settle_failed` logged 113 times in
  one night. Needs de-duplication/throttling (e.g. collapse repeats within a time window
  into one notification, or only notify on a state *transition* into "lost") before this
  reaches the UI as a toast/push notification.
- **mDNS didn't advertise on the production Pi** — worked fine on the dev machine; to
  investigate on real hardware. First boot that night also logged `mdns.not_advertising`
  (`reason: advertised_port is not set`) before the port setting took effect — check
  whether the plugin should fall back to the app's own listening port instead of requiring
  an explicit `advertised_port`.
- **Sequencer camera temperature/ramp settings are unused** — the task editor doesn't let
  you set a target sensor temperature or cooling ramp rate; add to `ExposureGroup`/`Lane`
  and apply it at task setup.
- **PHD2 log analyzer** — parse PHD2's own guide log inside astrolol (star mass, RMS,
  dither/settle events) instead of requiring a separate tool. New plugin or part of
  `plugins/phd2/`.
- **`eqmod.stop_move` can 500 instead of degrading gracefully** — `/mount/<id>/move`
  (stop) raised `TimeoutError`/`EqmodMountError: Mount error 2: Motor not stopped` as an
  unhandled 500 four times that night (`plugins/eqmod/mount.py::_stop_axis`,
  `protocol.py::set_motion_mode`). The driver should retry or report a clean device-error
  state instead of leaking a raw exception through the API; `astrolol/api/mount.py`'s
  `stop_move` has no handling for an EQMOD-specific failure mode.

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
per-frame guiding stats (events + FITS cards), guiding check before each frame, guiding
recovery loop, stalls (guiding, centering, autofocus) with timeout, retaking badly unguided
frames, autofocus (task start, filter change, after flip, temperature / time triggers),
session journal (JSONL per run, sessions API, time breakdown, CSV/Markdown export, Journal tab),
multi-camera lanes (primary-driven fit rule, per-lane autofocus, estimates, multi-camera editor),
named sequences (server library) and task file download/upload.

- **Frame analysis + FWHM autofocus trigger** — measure star FWHM/HFR on science frames
  (every Nth frame or a downsampled copy, to stay cheap on a Pi; the imager's per-frame star
  analysis is disabled today), record it per frame (events, journal, FITS), and refocus when
  FWHM rises above the post-autofocus baseline (e.g. +20 %) rather than a fixed value.
- **Global sequencer settings vs the meta-scheduler** — the autofocus time/temperature
  triggers (and other global "when" policies) overlap with what the meta-scheduler will
  decide; they may move into it or become per-task. Undecided.
- **Journal — later** — per-frame FWHM/HFR once frame analysis exists; guiding RMS graph per
  session (needs guide steps in the journal, sampled); a "night report" across several
  sessions of the same target.
- **Lanes — later** — a secondary-lane error currently stops every lane (in-flight frames
  discarded); a per-lane error policy could let the other cameras carry on. The efficiency
  estimate ignores download time (real runs usually do a little better than shown).
- **One runner per mount** — rigs with several mounts: one independent queue/runner per
  mount (models and routes are keyed so `runner_id = mount_id` can be added later).
- **MCP tool surface** — expose the `Sequencer` protocol methods as MCP tools
  (`sequencer_add_task`, `sequencer_start`, `sequencer_status`, …).
- **Decided** — a disconnected guider doesn't block the start (pre-flight warns); the run
  waits for guiding like any outage. The flip hour angle stays a sequencer setting.
- **Test isolation** — integration tests build real apps on the default data dir: they log
  into `~/.astrolol/astrolol.log` and use `/tmp/astrolol`. Point them at a tmp data dir.
- **Simulator setup for autofocus** — the CCD simulator only draws stars when it snoops a
  telescope: with the eqmod simulator, enable the eqmod INDI proxy and set the camera's
  `ACTIVE_DEVICES.ACTIVE_TELESCOPE` to "astrolol Mount Proxy" (a live INDI setting astrolol
  doesn't set yet — worth doing automatically when the proxy is enabled). Needs the `gsc`
  package (INDI PPA).
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
- **Sidebar clutter from set-and-forget plugins** — every plugin with a UI currently gets its
  own top-level sidebar entry (`plugin-registry.ts` + `manifest.nav_order`), which doesn't
  scale once small, configure-once plugins (e.g. `mdns`) pile up alongside the plugins people
  actually navigate to daily (sequencer, mount, imaging). Needs some notion of a lesser-tier
  plugin whose settings live in a subpage (e.g. folded into an "Options" or "Plugins" list)
  instead of claiming a permanent sidebar slot. Not designed yet — affects `PluginManifest`
  (a tier/category field?) and `plugin-registry.ts` (how the sidebar renders each tier).

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
- **Auth token** — bearer token, generated once, entered manually into the Android app;
  must work for both `GET`/`POST` (Authorization header) and the `/ws/events` WebSocket
  (query param or subprotocol, since browsers can't set arbitrary headers on a WS handshake);
  must survive a reverse proxy injecting the header. Required before any internet exposure.
  See the Security section in README.md.
