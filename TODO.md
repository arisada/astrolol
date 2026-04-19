# astrolol — deferred work

Items designed for but not yet built. Ordered roughly by priority.

## Near-term

- **Target: write OBJECT to FITS headers** — the active target name (when set) should be
  written as the `OBJECT` keyword in captured FITS files. `ImagerManager` already reads mount
  position for `RA`/`DEC` headers; extend it to also read `MountManager.get_target()`.
- **Simbad / NED name resolver plugin** — resolve an object name ("M31", "NGC 7293") to
  ICRS coordinates and call `PUT /mount/{id}/target` automatically.
- **Target persistence across restart** — store the last-set target in `profiles.json` so
  it survives a backend restart.

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

- **Sequencer** — state machine (idle → slewing → focusing → guiding → imaging → dithering).
  Cancellable at every step. PHD2 and plate-solve plugins already exist as building blocks.
  Strong plugin candidate.
- **Debayer + full STF preview** — colour camera preview shows raw Bayer grid today.
- **Calibration pipeline** — flat/dark/bias acquisition and application (ccdproc). Plugin.
- **Autofocus module** — V-curve fitting, backlash compensation, temperature compensation.
  Plugin.

## Mount — deferred

- **Watchdog** — periodic `ping()` calls on each connected device; transition to ERROR state
  and surface an alert in the UI without crashing the app.
- **Pointing model** — n-point alignment corrections stored per-profile.

## UI consistency audit

- **Shared connect/disconnect button pattern** — PHD2 page uses an inline variant-switching
  button while Equipment page uses a different pattern. Audit all pages (PHD2, Equipment,
  Focuser, Mount) and extract a shared `ConnectButton` component so styling is identical
  everywhere.
- **ToggleSwitch duplication** — defined locally in both `Mount.tsx` and `Phd2Page.tsx`.
  Extract to `ui/src/components/ui/toggle-switch.tsx` and import from both.

## Post-MVP

- **Persistence layer** — SQLAlchemy + aiosqlite + Alembic migrations. Session history,
  image metadata, autofocus run data.
- **UI: red mode** — CSS filter toggle for night vision preservation.
- **UI: mobile layout** — responsive breakpoints, bottom tab navigation on small screens.
- **Caddy / systemd packaging** — deployment guide for Raspberry Pi with HTTPS and autostart.
- **Auth / security** — API keys or JWT tokens. Required before any internet exposure.
  See the Security section in README.md.
