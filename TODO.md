# astrolol — deferred work

Items designed for but not yet built. Ordered roughly by priority.

## Done (recent)

- ~~**INDI adapters**~~ — `ICamera`, `IMount`, `IFocuser` in `astrolol/devices/indi/` using
  `indipyclient`. 191 unit tests + 34 integration tests against real INDI simulators.
- ~~**Equipment profiles**~~ — named device configs persisted to JSON (`ProfileStore`).
  CRUD endpoints, activate/deactivate, reconnect on startup.
- ~~**Friendly device IDs**~~ — auto-generated from driver name (e.g. `mount_eqmod_telescope`);
  user-supplied IDs validated for safe characters.
- ~~**Mount extras**~~ — tracking rate (sidereal/lunar/solar), `mount.operation_failed` event,
  `mount.unparked` event, pier side + hour angle in status, meridian flip button and endpoint.
- ~~**Plugin system**~~ — `Plugin` protocol, filesystem discovery under `plugins/`, enable/disable
  via `UserSettings.enabled_plugins`, `GET /plugins`, `POST /admin/restart`.
- ~~**Hello world plugin**~~ — full-stack PoC: `POST /hello/property`, React page, sidebar entry,
  Options toggle, 21 tests.

## Pre-release priorities

- **Watchdog** — per-device async task calling `ping()` periodically, transitions device to
  `DISCONNECTED` on repeated failure, publishes `device.state_changed` event. No crashes,
  clean user-facing errors on hardware loss.
- **Auth / security** — API keys or JWT tokens. Required before any internet exposure.
- **PHD2 integration** — async JSON-RPC client for guiding start/stop/status/events.
  Good candidate for a plugin.
- **Plate solving** — async subprocess wrapper for ASTAP / astrometry.net with progress
  events. Also a good plugin candidate.

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
- **Plugin dependency injection via EventBus** — plugins that need to talk to each other
  should publish/subscribe events rather than importing across plugin boundaries.
- **Plugin tests auto-discovered** — add `plugins/` to `testpaths` in `pyproject.toml` once
  there are enough plugins to justify it.

## Post-MVP

- **Sequencer** — state machine (idle → slewing → focusing → guiding → imaging → dithering).
  Cancellable at every step. Build watchdog + PHD2 first. Strong plugin candidate.
- **Persistence layer** — SQLAlchemy + aiosqlite + Alembic migrations. Session history,
  image metadata, autofocus run data.
- **Autofocus module** — V-curve fitting, backlash compensation, temperature compensation.
  Plugin.
- **Calibration pipeline** — flat/dark/bias acquisition and application (ccdproc). Plugin.
- **Debayer + full STF preview** — colour camera preview shows raw Bayer grid today.
- **UI: red mode** — CSS filter toggle for night vision preservation.
- **UI: mobile layout** — responsive breakpoints, bottom tab navigation on small screens.
- **Caddy / systemd packaging** — deployment guide for Raspberry Pi with HTTPS and autostart.
