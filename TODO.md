# astrolol — deferred work

Items designed for but not yet built. Ordered roughly by priority.

## Known bugs

- **Non-INDI equipment doesn't reconnect via Profiles** — an inventory item connected
  through a non-INDI adapter (e.g. `plugins/eqmod`'s `eqmod_sim`) shows up correctly in
  Inventory and in a Profile's device tree, but activating/reloading the profile does not
  bring it back online in the Connections tab. `Equipment.tsx`'s "Other adapter" wizard and
  the inventory/matching models (`EquipmentItem.adapter_key` / `connect_params`,
  `api/profiles.py::_find_device_for_item`) were updated to support non-INDI adapters, but
  `Profiles.tsx` was never audited — it likely has its own, separate logic for turning an
  inventory item into a connectable `DeviceConfig` when building/activating a profile, still
  assuming `indi_driver` / `indi_device_name`. Flagged as the first concretely observed
  symptom of a wider profiles/equipment audit that's still needed.

## Near-term

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

- **Debayer + full STF preview** — colour camera preview shows raw Bayer grid today.
- **Calibration pipeline** — flat/dark/bias acquisition and application (ccdproc). Plugin.

## Mount — deferred

- **Watchdog** — periodic `ping()` calls on each connected device; transition to ERROR state
  and surface an alert in the UI without crashing the app.
- **Pointing model** — n-point alignment corrections stored per-profile.

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
