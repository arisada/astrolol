# astrolol — deferred work

Items designed for but not yet built. Ordered roughly by priority.

## Pre-release

- **INDI adapter** — implement `ICamera`, `IMount`, `IFocuser` in `astrolol/devices/indi/`
  using `pyindi-client`. Bundled in the main package; registers via entry point in
  `pyproject.toml`. INDI simulator drivers replace hardware during development.
- **Equipment profiles** — persist named `DeviceConfig` lists to SQLite so users configure
  their rig once. CRUD endpoints + load-profile-at-startup flow.
- **Watchdog** — per-device async task that calls `ping()` periodically, transitions device
  to `DISCONNECTED` on repeated failure, publishes events. No crashes, clean user-facing errors.
- **Auth / security** — JWT tokens, API keys, TOTP/2FA. Required before any internet exposure.
- **PHD2 integration** — async JSON-RPC client for guiding start/stop/status/events.
- **Plate solving** — async subprocess runner for ASTAP / astrometry.net with progress events.

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
