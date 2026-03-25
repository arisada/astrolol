# astrolol — deferred work

Items that are designed for but not yet built. Ordered roughly by priority.

## Pre-release

- **Equipment profiles** — persist named `DeviceConfig` lists to SQLite so users configure their rig once. CRUD endpoints + load-profile-at-startup flow.
- **Watchdog** — per-device async task that calls `ping()` periodically, transitions device to `DISCONNECTED` on repeated failure, publishes events. No crashes, clean user-facing errors.
- **Auth / security** — JWT tokens, API keys, TOTP/2FA. Required before any internet exposure.
- **INDI plugin** (`astrolol-indi` package) — concrete `ICamera`, `IMount`, `IFocuser` adapters via `pyindi-client`.
- **PHD2 integration** — async JSON-RPC client for guiding start/stop/status/events.
- **Plate solving** — async subprocess runner for ASTAP / astrometry.net with progress events.

## Post-MVP

- **Persistence layer** — SQLAlchemy + aiosqlite + Alembic. Session history, image metadata, autofocus run data.
- **Image preview pipeline** — FITS → stretched JPEG server-side (NumPy + Pillow), streamed to clients over WebSocket.
- **Autofocus module** — V-curve fitting, backlash compensation, temperature compensation.
- **Flat/dark/bias calibration** — ccdproc-based pipeline.
- **Plugin hooks for sequence steps** — expose `register_sequence_steps` hookspec once there are two implementations worth abstracting.
- **Caddy / systemd packaging** — deployment guide for Raspberry Pi with HTTPS and autostart.
