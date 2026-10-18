# astrolol — deferred work

Items designed for but not yet built. Ordered roughly by priority.

## Known bugs

- **INDI items connected from the tree are untested on real indiserver** — the mapping
  (`indi_<kind>` + `{device_name, executable}`) matches what the wizard sends and the INDI
  adapters load the driver themselves, but only non-INDI items were verified end to end.
- ~~PHD2 guides the wrong way in Dec after a meridian flip~~ — **root-caused via the
  2026-10-05 PHD2 guide/debug logs, not an astrolol bug.** PHD2's mount is correctly set to
  "INDI Mount [astrolol Mount Proxy]", and that proxy reports `TELESCOPE_PIER_SIDE` correctly
  throughout (confirmed in code and in the logs). At 19:55:37 PHD2 detected the flip
  ("Guiding starts on opposite side of pier: calibration data side is West, current side is
  East") and auto-adjusted calibration, but only flipped the RA angle (71.6° → -108.4°) and
  left Dec unchanged (164.7° → 164.7°, logged as `decFlipRequired=0`) — hence the inverted Dec
  guiding and the "PHD2 is not able to make sufficient corrections in Dec" alerts a few minutes
  later. A manual recalibration on the East side measured the true Dec angle at -15.3°, which
  is exactly 164.7° − 180°, proving Dec genuinely needed the flip that PHD2 skipped.
  **Fix: enable "Reverse Dec output after meridian flip" in PHD2's own Advanced Settings →
  Guiding tab.** This is a one-time PHD2-side setting, not an astrolol code change — nothing
  here needs patching.
- **Reconnecting a device after a USB glitch doesn't show up for freshly opened clients** —
  observed after a USB disconnect/reconnect mid-session: the already-open window keeps
  showing the mount (stale, pre-refresh state), but a *new* browser window/tab never shows
  the mount panel at all, even though `DeviceManager.list_connected()` /
  `GET /devices/connected` return the reconnected device correctly on the backend. Likely
  culprit is whatever UI hook fetches the device list on initial mount of a new window/tab
  (not yet located — check `ui/src/hooks` and the WS `device.connected`/`device.disconnected`
  handling in `ui/src/store/index.ts`) silently keeping a device filtered out, or a race with
  the WS event ordering. Needs reproduction + a known device id to trace through the store.

## From the 2026-10-17 night session

Fixed the next day: Moon/planets/Sun resolved to the wrong place (the resolver converted the
geocentric position to ICRS, which for a body with a distance is the direction seen from the
solar-system barycentre — the Moon came out ~97° off; the target page's Moon separation had the
same bug) and bright stars had no names (Hipparcos only has numbers; `star_names.py` now adds the
IAU names as aliases, also to catalogues synced earlier).

- **A slew went below the horizon.** The only check is `MountManager._check_above_horizon`, and it
  silently does nothing when the active profile has no Site item (`horizon_min_alt_deg` is also 0 by
  default). Not reproducible here: needs the Pi's `astrolol.log` of that night (look for
  `mount.slew_started` and which profile/site was active). At least log a warning when the check is
  skipped for lack of a site; consider falling back to the latitude/longitude the mount reports.
  The Moon bug above may have contributed (wrong coordinates were checked, not the real Moon).
- **Nudge cross: release events sometimes lost** (mount keeps moving or the button stays pressed).
  Fix the existing cross (pointer capture / `pointercancel` / blur / visibility loss all stop the
  nudge, server-side dead-man timeout) and design a mobile-first one.
- **"What to watch tonight" list** — suggested targets for the site and date: above the horizon long
  enough, away from the Moon, ranked (size vs. field of view, brightness, altitude window). Needs
  magnitude/size in the catalogue (Hipparcos Vmag is downloaded but not stored; OpenNGC has sizes).
- **Target type filter** — checkboxes in the target search (galaxies, clusters, nebulae, stars,
  solar system, …) on the catalogue's `object_type`.
- **Moon accuracy** — positions are geocentric: topocentric parallax is up to ~1° for the Moon
  (needs the site). A GOTO to the Moon/planets then tracks at the sidereal rate; add lunar and
  planetary tracking rates (eqmod and INDI).
- **Star names as primary names** — a search for "Vega" returns "HIP 91262" with Vega as an alias;
  show the proper name first, and add the fainter named stars (the list has ~110).
- **Catalogue is only downloaded when empty** — an old database never picks up catalogue changes;
  add a schema/data version and a refresh (UI button exists via `POST /sync`, nothing automatic).

## EQMOD native driver — assumptions & deferred items

Phase 2 (`astrolol/plugins/eqmod/`) deliberately starts narrow. Each item below is an assumption
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

- **Polar-align planning assumes "same side of the meridian ⇒ same pier side"** — true
  for a German mount in its normal, counterweight-down position, which is the usual
  starting state. A mount that is *currently* tracking past the meridian
  (counterweight-up) gets planned on its Hour-Angle side, so the first GoTo flips it and
  the existing post-slew pier-side check aborts the run (safe, but unhelpful). Fix: plan
  from `MountStatus.pier_side` when it's known instead of the HA sign alone.
- **Polar-align preflight conditions on the true pole, not the real axis** —
  `plan_targets` predicts the CONVERGING reference's conditioning margin with the true
  pole standing in for the not-yet-fitted axis, accepting any margin > 0. A mount several
  degrees off could land a marginal reference just inside a guard zone; the recheck then
  fails visibly (now logged and shown in the UI) rather than silently. A fix would require
  a minimum margin scaled to the expected rough-alignment error, or a re-plan of the
  reference point after the fit.
- ~~Autofocus star detector picks up hot pixels, especially on defocused frames~~ and
  ~~FWHM metric performs much worse than HFD~~ — **fixed (15545bb).** Stars are now found by
  scale-space blob detection (any size, sharp to ~90 px), isolated hot pixels are cleaned first,
  and HFD is the default metric. Checked end to end on the INDI CCD/focuser simulators
  (`astrolol/plugins/autofocus/tests/test_autofocus_simulator.py`). Remaining autofocus work:
  - **Choose the reference stars at the best-focus frame**, not at step 1 (the most defocused
    frame when the sweep starts far off), then re-measure every frame at those fixed positions
    after the sweep so a star too faint to detect at the far end still gets a measurement.
    Live progress would show the quick per-frame value first.
  - **Reject sweep steps with too few valid stars** in the engine (e.g. under half the
    reference stars), instead of accepting any `star_count > 0`, and report skipped points.
  - **Hot-pixel map from dark frames** — let the user register darks to identify known hot
    pixels; the detector already cleans unknown ones but a map is exact. Feed it into
    `_suppress_hot_pixels`.
  - **`fit_hyperbola` rejects wide, nearly pure-V sweeps** — on the simulator (size 3 → 34 px
    over 80 000 steps) the fitted y² parabola dips just below zero at its minimum and the
    `c - b²/4a < 0` check rejects it. The default parabola fit works.
  - **Saturated stars are measured too wide** (FWHM 4–9 px for a true 3 px) because the
    clipped core shifts the moments and the HFD. Exclude stars with clipped pixels.
  - **Hot-pixel cleaning is only verified on synthetic frames** (the simulator has none) —
    check on a real camera, including the 0.12 neighbour ratio and the sharp-star case.
  - **Undersampled stars (FWHM under ~1.6 px)**: the moment-based FWHM is quantised by pixel
    sampling near focus; HFD is steadier. Consider dropping FWHM as a choice in the UI.
- **Resuming a sequencer task after a crash skips re-plate-solving** — a crash mid-task
  should be treated like a long pause on the next startup (force `setup_needed=True` so
  `_setup()`'s slew/center/plate-solve runs again), not resume straight into exposing at
  the last known pointing.
- **Too many PHD2 "star lost" notifications** — `phd2.settle_failed` logged 113 times in
  one night. Needs de-duplication/throttling (e.g. collapse repeats within a time window
  into one notification, or only notify on a state *transition* into "lost") before this
  reaches the UI as a toast/push notification.
- **mDNS didn't advertise on the production Pi** — worked fine on the dev machine; to
  investigate on real hardware. (The "advertised_port is not set" case that first boot hit is
  gone: the port now defaults to 8000.) Suspect: Avahi already owns `<hostname>.local` on the
  Pi while zeroconf also publishes records for it — check for a name conflict in the logs.
- **Sequencer camera temperature/ramp settings are unused** — the task editor doesn't let
  you set a target sensor temperature or cooling ramp rate; add to `ExposureGroup`/`Lane`
  and apply it at task setup.
- **PHD2 log analyzer** — parse PHD2's own guide log inside astrolol (star mass, RMS,
  dither/settle events) instead of requiring a separate tool. New plugin or part of
  `astrolol/plugins/phd2/`.
- **`eqmod.stop_move` can 500 instead of degrading gracefully** — `/mount/<id>/move`
  (stop) raised `TimeoutError`/`EqmodMountError: Mount error 2: Motor not stopped` as an
  unhandled 500 four times that night (`astrolol/plugins/eqmod/mount.py::_stop_axis`,
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

## Built-in guider — remaining work

Done (`astrolol/plugins/guider/`): native INDI camera streaming (`IStreamingCamera`), pulse
guiding through the camera's ST4 output or the mount (`IPulseGuider`, selectable, camera by
default), star detection/selection (saturation-aware, click a star in the UI), dark frames,
windowed multi-star tracking with re-acquisition (nearest look-alike, then pattern match over
the full frame), binning, calibration (one global least-squares fit, quality checks, backlash,
saved to disk, adjusted to the mount's declination and pier side, learned Dec flip), guards
against glitches (jump check), wrong-way axes (reversal check), refused pulses, camera stalls
and slews, drift + periodic-error prediction on RA (`predictor.py`), per-axis tuning in the
UI, dither, settle, REST API and UI page. Verified against INDI's simulators on both routes
(2026-10-13); the quirks found there are in the project memory ("guider known quirks").

- **Real hardware and a Pi** — never run on a real camera/mount. To do on the first clear
  night: calibrate near the equator and check the quality warnings; watch the log for
  `axis_reversed`, `star_moved`, `pulse_failed`; guide over two worm periods to see whether the
  periodic error is found. Detection and the per-frame loop (incl. the predictor's period
  search) haven't been timed on a Raspberry Pi.
- **Meridian flip on a real mount** — the "auto" Dec-flip guess (camera ST4 keeps Dec, mount
  route reverses it) matches the simulators only; confirm on the user's mount.
- **Mount route on the simulator** — guides rougher (~1.8 px vs ~0.3 px RMS via camera ST4)
  because the Telescope Simulator applies pulses late and in batches. Re-measure on a real
  mount before tuning anything for it.
- **Integration test with periodic error** — the slow INDI test proves stability, not the gain
  from prediction; the sims do have PE (~40 px p-p over ~480 s), so a long run could assert the
  period is found and RMS falls. Costs more than two worm periods of real time.
- **Min-move from the seeing** — "auto" min move is from the pixel scale (~0.3"); deriving it
  from the measured star-position noise per axis would adapt to the night.
- **Dec backlash from guiding history** — compensation is off by default; the learned share
  resets every run. Measure it from overshoot after reversals and keep it across runs.
- **Resist-switch frame count / fast-switch factor** are still code constants, not settings.
- **Other algorithms** — *LowPass2* (encoder mounts, low priority); *Z-filter* (rarely beats
  LowPass2, skip unless short exposures matter).
- **Dark capture UX** — the scope has to be covered by hand; no prompt-and-wait flow, and
  darks for the sequencer's own camera aren't shared.
- **Guiding data in the event stream, not polled** — the dock's guide target/graph widgets
  (`astrolol/plugins/guider/ui/GuiderWidgets.tsx`) and the guider page poll `GET /status`
  (every 2 s / 1 s) for the last-minute RMS and the pixel scale (px vs arcsec). Put them on the
  stream instead: add the pixel scale and the running RMS (RA/Dec/total) to `guider.step` (or a
  periodic `guider.stats` event), keep them in the plugin's `pluginStates` slice, and drop the
  polling from the widgets. The page's other polled data (calibration, settings) can follow.

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
- **A secondary lane whose duration is close to the primary's genuinely can't reach full
  efficiency, and the preflight is right to say so** — `estimate_lanes()` in
  `astrolol/plugins/sequencer/lanes.py` requires `duration + margin_s <= interval` for a secondary
  frame to fit, with no exemption for "the first frame since the last dither" — and that's
  correct, because `RigSchedule.fits()` (the actual runtime gate the primary/secondary
  lanes use to decide when a secondary frame may start) enforces the exact same inequality
  with no such exemption either (`clock() + duration + margin <= next_mount_op()`). Two
  lanes of equal duration with `margin_s > 0` (the default `download_margin_s` is 10s) will
  really stall forever in `WAITING_FOR_PRIMARY` at runtime, not just get a pessimistic
  preflight number — confirmed by tracing `fits()` directly. A real fix for "I want two
  cameras of the same exposure length to run together" would teach *both* layers a new
  rule — the first secondary frame attempted since the primary's last dither doesn't need
  `margin` of its own (it finishes in lockstep with the primary, which isn't charged a
  margin against itself either), only the 2nd+ frame squeezed into the same interval does.
  That requires `RigSchedule` to track, per secondary lane, which dither-cycle it last
  placed a frame in (a monotonic dither counter, bumped wherever the primary's own dither
  actually fires) — a real scheduler change, not a one-line math fix, and one that needs
  care given it directly gates mount/camera timing. (A previous attempt fixed only the
  preflight math without touching `RigSchedule`, which made the estimate lie instead —
  caught by `/code-review` before it shipped.)
- **`estimate_lanes()` fits each group in a multi-group lane independently, overcounting
  shared interval slots** — a lane with alternating groups (e.g. round-robin R/G) gets
  each group's `per_interval` computed as if it alone had the whole interval to itself,
  so the estimate can promise more total frames than the interval can actually hold
  across all of a lane's groups combined (pre-existing, not introduced by the item
  above — confirmed present with or without that fix). Needs the per-group loop to share
  one interval budget across the whole lane instead of computing each group in isolation.
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

## Bluetooth serial — deferred

- **INDI mounts over Bluetooth** — `astrolol/plugins/bluetooth_serial` + `astrolol/devices/bluetooth/`
  currently only serve native (non-INDI) drivers, which open a raw RFCOMM socket directly
  (see `BluetoothRfcommTransport`, used by `astrolol/plugins/eqmod`). An INDI driver process needs an
  actual `/dev/rfcommN` tty node, which BlueZ's D-Bus API can't create — that still needs the
  `rfcomm connect` subprocess approach discussed when this was designed, exposed as a device
  so it can sit in a profile and be waited on the same way a USB-serial port would.
- **Single Bluetooth adapter assumed** — `BlueZBackend` hardcodes `/org/bluez/hci0`; a second
  adapter (`hci1`) isn't selectable.
- **Not tested**: re-pairing after a lost link key, pairing more than one device in the same
  session, PIN/passkey flows other than the legacy fixed-PIN path (SSP "just works"/
  confirmation path is implemented but unverified against real hardware).

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
- **Packaging** — `deploy/` has a systemd unit, nginx configs for HTTP/HTTPS and
  `install-nginx-https.sh`; `docs/raspberry-pi-deployment.md` is the guide. Still missing:
  - **PyPI release**: ship the built UI inside the wheel (`static.py` only looks next to
    the source tree or in `ASTROLOL_UI_DIST`), and publish or bundle `indipyclient`
    (PyPI rejects the `vendor/` direct reference). Then the guide's checkout and UI build
    steps go away, and the System page's Development section (git pull) needs a pip-based
    equivalent.
  - A single installer for the service user, venv and systemd unit.
  - A Caddy alternative (automatic certificates) and a trusted-certificate path
    (Let's Encrypt / local CA) instead of self-signed.
  - A `.deb` or SD-card image.
- **Security plugin — follow-ups.** First version shipped (`astrolol/plugins/security/`:
  users with viewer/operator/admin, guest mode, API tokens, allowed origins, loopback service
  token for the INDI mount proxy). Still open:
  - **Prevent disabling the plugin once users exist.** Disabling it today silently opens the
    API again (and hides the Security page). Decide how: refuse in `PUT /settings`, require a
    recovery CLI, or keep enforcement in core independent of the plugin.
  - **WebSocket auth for non-browser clients.** They send `Authorization: Bearer` in the
    handshake; browsers can't, but use the session cookie. A short-lived ticket endpoint
    would help clients that cannot set headers.
  - **Unauthenticated TCP listeners.** LX200, Stellarium and the INDI server accept anyone who
    can reach the port; give them bind-address / allowed-client settings.
  - **Host allowlist** (DNS rebinding) is unnecessary once sign-in is on, but matters while
    the API is open.
  - Per-user preferences (language, theme): only admins can write settings today.
  - Audit `operator`-reachable settings for anything that can run commands or point at
    arbitrary paths (rule: those are admin-only, see each plugin's `acl_rules`).
  - Session idle timeout / "sign out everywhere" button; login audit log in the UI.
