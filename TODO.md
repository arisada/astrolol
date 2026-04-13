# astrolol — deferred work

Items designed for but not yet built. Ordered roughly by priority.

## Pre-release

- ~~**INDI adapter**~~ — **Done.** `ICamera`, `IMount`, `IFocuser` implemented in
  `astrolol/devices/indi/` using `indipyclient` (pure Python asyncio). 108 tests pass
  including 34 integration tests against real INDI simulators.
- **Equipment profiles** — persist named `DeviceConfig` lists to SQLite so users configure
  their rig once. CRUD endpoints + load-profile-at-startup flow.
- **Watchdog** — per-device async task that calls `ping()` periodically, transitions device
  to `DISCONNECTED` on repeated failure, publishes events. No crashes, clean user-facing errors.
- **Auth / security** — JWT tokens, API keys, TOTP/2FA. Required before any internet exposure.
- **PHD2 integration** — async JSON-RPC client for guiding start/stop/status/events.
- **Plate solving** — async subprocess runner for ASTAP / astrometry.net with progress events.

## Profiles — deferred

- **Profile duplication** — Clone button on each ProfileCard that POSTs a copy with a new UUID and name suffix " (copy)".
- **Import / export profiles** — download `profiles.json` as a file; upload to merge or replace. Useful for backup and sharing equipment configs between machines.
- **Map picker for location** — embed a Leaflet or similar map in the location editor so users can click to set coordinates instead of typing them.

## Mount — deferred

- ~~**Background task error events**~~ — Done. `mount.operation_failed` published on slew/park timeout or error; `mount.unparked` event also added.
- ~~**Tracking rate backend**~~ — Done. `TrackingRequest` now accepts `mode: sidereal | lunar | solar`; INDI adapter sets `TELESCOPE_TRACK_RATE` before toggling tracking.

## Post-MVP

- **Sequencer** — state machine (idle → slewing → focusing → guiding → imaging → dithering).
  Cancellable at every step. The sequencer is the most complex module; build INDI + profiles
  + watchdog first.
- **Persistence layer** — SQLAlchemy + aiosqlite + Alembic migrations. Session history,
  image metadata, autofocus run data, equipment profiles.
- **Autofocus module** — V-curve fitting, backlash compensation, temperature compensation.
- **Calibration pipeline** — flat, dark, bias frame acquisition and application (ccdproc).
- **Debayer + full STF preview** — colour camera preview currently shows raw Bayer grid.
  Add debayer and ScreenTransferFunction stretch for colour cameras.
- **UI: red mode** — CSS filter toggle for night vision preservation.
- **UI: mobile layout** — responsive breakpoints, bottom tab navigation on small screens.
- **Plugin hooks for sequence steps** — expose `register_sequence_steps` hookspec once
  there are two implementations worth abstracting.
- **Caddy / systemd packaging** — deployment guide for Raspberry Pi with HTTPS and autostart.
