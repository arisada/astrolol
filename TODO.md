# astrolol — deferred work

Items designed for but not yet built. Ordered roughly by priority.

## Pre-release priorities

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

## Imaging — deferred

- **Observation target** — introduce a `Target` concept (RA/Dec J2000 + optional object name
  looked up from a catalogue, e.g. "M31", "NGC 7293").  A target is distinct from the mount's
  current reported position: the mount may be slightly off after a GoTo, and a target can be
  set before the mount has finished slewing.  The active target should be stored in
  `MountManager` and written as `OBJECT` in FITS headers.  A Simbad/NED name-resolver plugin
  would populate the object name automatically.

## UI consistency audit

- **Shared connect/disconnect button pattern** — PHD2 page uses an inline variant-switching
  button while Equipment page uses a different pattern. Audit all pages (PHD2, Equipment,
  Focuser, Mount) and extract a shared `ConnectButton` component so styling is identical
  everywhere.
- **ToggleSwitch duplication** — defined locally in both `Mount.tsx` and `Phd2Page.tsx`.
  Extract to `ui/src/components/ui/toggle-switch.tsx` and import from both.

## Post-MVP

- **Sequencer** — state machine (idle → slewing → focusing → guiding → imaging → dithering).
  Cancellable at every step. Build PHD2 first. Strong plugin candidate.
- **Persistence layer** — SQLAlchemy + aiosqlite + Alembic migrations. Session history,
  image metadata, autofocus run data.
- **Autofocus module** — V-curve fitting, backlash compensation, temperature compensation.
  Plugin.
- **Calibration pipeline** — flat/dark/bias acquisition and application (ccdproc). Plugin.
- **Debayer + full STF preview** — colour camera preview shows raw Bayer grid today.
- **UI: red mode** — CSS filter toggle for night vision preservation.
- **UI: mobile layout** — responsive breakpoints, bottom tab navigation on small screens.
- **Caddy / systemd packaging** — deployment guide for Raspberry Pi with HTTPS and autostart.
