# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Headless, async, modular Python astronomy platform. Think AsiAir but open source.
Runs on a machine attached to the telescope (e.g. Raspberry Pi). Clients (web, mobile, native)
connect via REST and WebSocket. The backend owns all state — clients are observers.

## Architecture in one paragraph

FastAPI serves the REST and WebSocket API. Devices (camera, mount, focuser, filter wheel) are
abstracted behind `Protocol` interfaces in `astrolol/devices/base/`. Concrete adapters register
themselves via the pluggy plugin system at startup. Standard adapters (INDI) are **bundled
inside astrolol** in `astrolol/devices/indi/` — the pluggy interface exists for extensibility,
not to force a separate install for the common case; `plugins/eqmod/` is a real example of a
non-INDI adapter (a native serial driver for Sky-Watcher motor controllers) that also exposes
an INDI proxy so INDI-only clients (e.g. PHD2) can still guide through it. Similarly,
`astrolol/core/guiding/` and `astrolol/core/sequencer/` define guider- and sequencer-agnostic
`Protocol` contracts that `plugins/phd2/` / `plugins/guide_simulator/` and `plugins/sequencer/`
implement. An internal `EventBus` (asyncio queues) lets any component publish typed events;
connected WebSocket clients subscribe and receive a live JSON stream. A React + TypeScript web
UI is served as static files from `ui/dist/` and proxied through Vite in development.

## Plugin architecture

**New features should go in `plugins/` whenever possible.** A plugin is a self-contained
directory with its own API, UI component, sidebar entry, and tests. The core wires them in
at startup based on `UserSettings.enabled_plugins`.

```
plugins/
└── my_feature/
    ├── __init__.py
    ├── plugin.py          # class MyPlugin + get_plugin() factory
    ├── api.py             # FastAPI router, registered in plugin.setup()
    ├── ui/
    │   ├── index.ts       # default export: { icon, label, Component, StatusChip? }
    │   ├── MyPage.tsx     # React page, imported via @plugins alias
    │   ├── MyChip.tsx     # optional status-bar chip
    │   └── api.ts         # plugin-local fetch helpers (mirrors api.py routes)
    └── tests/
        └── test_my_api.py
```

- **`plugin.py`** must export `get_plugin() -> Plugin` and a class satisfying the
  `Plugin` protocol (`astrolol/core/plugin_api.py`): `manifest`, `setup()`, `startup()`, `shutdown()`.
- **`setup(app, ctx)`** is called once at startup for each enabled plugin. Register routes here.
  Use `app.state` to store plugin-scoped state — never module-level globals (breaks test isolation).
- **`PluginContext`** provides `event_bus`, `device_manager`, `device_registry`. Plugins must not
  import from each other directly; use the EventBus for inter-plugin communication.
- **`nav_group`** (manifest) puts the plugin's page in a navigation category: `equipment` (drivers, simulators, protocol bridges), `astronomy` (default: observing features) or `settings` (host/system). Options → Plugins groups by it too.
- **Enabling/disabling** requires a restart (`POST /admin/restart` or restart the process).
  `UserSettings.enabled_plugins` is persisted in `profiles.json`.
- See `plugins/hello/` for a minimal example; `plugins/autofocus/` for a full-stack example.

**Core code** (`astrolol/`) is for infrastructure: device adapters, event bus, profile store,
settings, API wiring. Features with UI, their own API routes, and optional enable/disable belong
in plugins.

## Plugin UI guidelines

### The hard rule: plugins never touch core UI files

`ui/src/api/client.ts`, `ui/src/store/index.ts`, `ui/src/components/StatusBar.tsx`, and similar
core files must not be modified to add plugin-specific logic. Everything a plugin needs must be
registered at runtime through the extension points described below.

### Plugin UI file layout

Every plugin with a UI must have `plugins/<id>/ui/index.ts` as its entry point:

```ts
// plugins/my_feature/ui/index.ts
import { SomeIcon } from 'lucide-react'
import { MyPage } from './MyPage'
import { MyChip } from './MyChip'          // optional
import { registerPluginEventHandlers } from '@/store'

registerPluginEventHandlers('my_feature', { /* ... see below */ })

export default {
  icon: SomeIcon,
  label: 'My Feature',
  Component: MyPage,
  StatusChip: MyChip,   // omit if the plugin has nothing to show in the status bar
}
```

Vite eagerly imports all `@plugins/*/ui/index.ts` files at build time (see `plugin-registry.ts`).
Any side-effects in `index.ts` — like `registerPluginEventHandlers` — run once at startup.

### API client

Each plugin owns its own `ui/api.ts` with typed fetch helpers that mirror its backend routes.
Do **not** add plugin routes to `ui/src/api/client.ts`. Copy the `request<T>` helper into the
plugin's `api.ts` rather than importing it from the core (it is not exported).

```ts
// plugins/my_feature/ui/api.ts
import type { MySettings } from '@/api/types'

async function request<T>(path: string, options?: RequestInit): Promise<T> { /* ... */ }

export const getSettings = () => request<MySettings>('/plugins/my_feature/settings')
export const putSettings = (s: MySettings) =>
  request<MySettings>('/plugins/my_feature/settings', { method: 'PUT', body: JSON.stringify(s) })
```

Type definitions that describe backend models (Pydantic → TS) belong in `ui/src/api/types.ts`
because `useEvents` / the store may reference them when deserialising WebSocket events.
Everything else (local UI state shapes, constants) lives inside the plugin directory.

### Persisting plugin settings

Store plugin settings in `UserSettings.plugin_settings` (a `dict[str, dict]` keyed by plugin id).
Expose `GET /plugins/<id>/settings` and `PUT /plugins/<id>/settings` from the plugin's `api.py`:

```python
@router.get("/settings", response_model=MySettings)
async def get_settings(request: Request) -> MySettings:
    raw = request.app.state.profile_store.get_user_settings().plugin_settings.get("my_feature", {})
    return MySettings(**raw)

@router.put("/settings", response_model=MySettings)
async def put_settings(body: MySettings, request: Request) -> MySettings:
    store = request.app.state.profile_store
    current = store.get_user_settings()
    updated = {**current.plugin_settings, "my_feature": body.model_dump()}
    store.update_user_settings(current.model_copy(update={"plugin_settings": updated}))
    return body
```

The UI page loads settings on mount and saves them before any long-running operation starts
(not on every keystroke — a single PUT before `start` is enough).

### WebSocket events and the Zustand store

Plugins must not add their own fields to the core `AppState` in `ui/src/store/index.ts`.
Instead, register event handlers from `index.ts` using `registerPluginEventHandlers`:

```ts
import { registerPluginEventHandlers } from '@/store'
import type { AstrolollEvent } from '@/api/types'

interface MyRunningState { step: number; total: number }

registerPluginEventHandlers('my_feature', {
  'my_feature.started': (_event, _cur): MyRunningState => ({ step: 0, total: 10 }),
  'my_feature.progress': (event, cur) => {
    const e = event as Extract<AstrolollEvent, { type: 'my_feature.progress' }>
    return { ...(cur as MyRunningState), step: e.step }
  },
  'my_feature.completed': () => null,   // null clears the state
  'my_feature.failed':    () => null,
})
```

Handler contract:
- `(event, currentPluginState) => newState | null | undefined`
- `undefined` — no state update (handler opted out for this event)
- `null` — explicitly clear the plugin's state slice
- any other value — replaces the plugin's state slice

Plugin state is stored under `useStore((s) => s.pluginStates['my_feature'])`. Cast it to your
interface inside the component; the store holds it as `unknown` to avoid coupling.

### Shared UI components

Use components from `ui/src/components/ui/` rather than re-implementing them per plugin:

| Component | Import | Description |
|---|---|---|
| `EventLog` | `@/components/ui/event-log` | Scrollable log panel filtered by component name(s) |
| `PillGroup` | `@/components/ui/pill-group` | Segmented button group for enum-like or numeric options |
| `DurationStepper` | `@/components/ui/duration-stepper` | Number input with +/− stepper buttons |
| `CountStepper` | `@/components/ui/count-stepper` | Frame-count stepper (0,1,2,3,5,10,… steps), editable inline |
| `Input` | `@/components/ui/input` | Styled text/number input |
| `ToggleSwitch` | `@/components/ui/toggle-switch` | Labelled boolean toggle |
| `Card`, `SidebarSection` | `@/components/ui/card` | Container variants |
| `Badge`, `Chip`, `StatusPill` | `@/components/ui/badge` | Status indicators |
| `Tabs` | `@/components/ui/tabs` | Segmented tab switcher |
| `DmsInput` | `@/components/ui/dms-input` | Dec/RA/lat/lon entry: joined DMS/HMS block, up/down per field, carry and clamping |
| `EquatorialSky`, `HorizontalSky` | `@/components/ui/mount-equatorial`, `mount-horizontal` | Mount position on the sky (centred on the pole, or on the zenith); take `latitude`, `lst`, `ra`, `dec` |
| `CoolingGauge` | `@/components/ui/cooling-gauge` | Sensor temperature, set point and cooler power as two half circles |
| `FocuserRuler` | `@/components/ui/focuser-ruler` | Graduated focuser position with target and optional initial marker |
| `GuideGraph`, `GuideTarget` | `@/components/ui/guide-graph`, `guide-target` | Guide error over time (RA/Dec lines, RMS band) and the recent positions around the aim point; take `GuideSample[]` (`ra`, `dec`, `ts`), a `range` and a `unit`. Helpers in `@/utils/guiding` |

```tsx
import { EventLog } from '@/components/ui/event-log'
import { PillGroup } from '@/components/ui/pill-group'

<EventLog filter={['my_feature', 'indi']} />
<PillGroup options={[1, 2, 4]} value={binning} onChange={setBinning} label="Binning" />
```

Tailwind design tokens are defined in `ui/tailwind.config.js`. Use only tokens defined there —
undefined tokens silently render as transparent without any build error.
Valid surface tokens: `bg-surface` · `bg-surface-raised` · `bg-surface-overlay` · `bg-surface-border`.

**Colours are palette-driven.** The palette is a user setting (Options → Palette, `UserSettings.theme`).
Every Tailwind colour is a CSS variable defined in `ui/src/themes.css`, which is *generated* by
`ui/scripts/gen-themes.mjs` (`npm run gen:themes`) — edit the script, never the CSS. The stock names
(`slate`, `sky`, `emerald`, `amber`, `rose`, `red`, `violet`, …; shades 100–900 only) are redirected to the
active palette, so the chip recipes below keep working. Rules:
- Never hard-code a hex/rgb colour in TSX. In SVG use classes (`stroke-slate-700`, `fill-surface`,
  `stroke-series-1`) or `rgb(var(--c-slate-400) / 0.5)`.
- Two chart series that stay distinguishable in every palette: `series-1` / `series-2`. Six categorical
  colours: `cat-1` … `cat-6`.
- Text on an accent background is `text-accent-fg`, not `text-white`.
- Never convey state by colour alone — the red night palettes make hues indistinguishable.

### Status-bar chips

If a plugin has activity worth surfacing globally (an ongoing run, a background task), export a
`StatusChip` component from `index.ts`. The `StatusBar` renders all plugin chips automatically —
no changes to `StatusBar.tsx` are needed.

The chip is responsible for deciding when to return `null` (when the plugin is idle). Render it with
the shared `Chip` (`@/components/ui/badge`) — never hand-roll the markup, the status bar styles
it as a hairline-separated telemetry readout (`LABEL value`):

```tsx
<Chip label={t('chip.guiding')} status={t('chip.settling')} variant="amber" pulse />
// variant: amber ← in progress / moving · green ← done / tracking · blue ← exposing / busy
//          violet ← solving / computing · red ← fault · slate ← idle
// optional: icon={<Crosshair …/>}; omit label for an icon + value chip
```

The status text always states the state in words; the colour is only a second cue. Add `pulse`
for states that are actively progressing.

### User-facing copy

Plugin manifest `description`, page headers/body text, button labels, and tooltips are
read by a user deciding what a feature does for them — not by a reviewer checking how it's
built. Say what the feature does and, if useful, why it matters to them. Leave out the
implementation detail that justified a design decision (a protocol name, a format, "so no
MAC address is needed", "stored in a dict keyed by plugin id") — that belongs in a code
comment or commit message, not in copy the user reads.

```
Bad:  "Advertises this astrolol server on the local network via mDNS (_astrolol._tcp.local.)
       so clients can find it without a typed-in IP."
Good: "Advertises this astrolol server on the local network via mDNS."
```

If you're tempted to write "(so that ...)" or "(no X to type/configure)" in a label or
description, that's usually the tell — cut it, or move it to a code comment.

### Internationalisation (i18n)

The UI uses `i18next` + `react-i18next`. English is the source language and the fallback;
French is the first translation. The language is a `UserSettings.language` field, chosen in
Options. Catalogues are JSON, nested by meaning (`mount.park.title`), with `_one`/`_other`
suffixes for plurals and `<tag>…</tag>` + `<Trans>` for inline markup.

| Where | Catalogue | Namespace |
|---|---|---|
| Core page or area | `ui/src/locales/<lng>/<ns>.json` | `equipment`, `profiles`, `imaging`, `mount`, `logs`, `options`, `events` |
| Shell + shared components | `ui/src/locales/<lng>/common.json` | `common` (default) |
| A plugin | `plugins/<id>/ui/locales/<lng>.json` | the plugin id |

- **Never hard-code user-visible text in TSX.** Use `const { t } = useTranslation('<ns>')`.
  That covers labels, placeholders, `title`/`aria-label`, empty states, button text and
  error text the UI itself writes. Backend-supplied text (driver/INDI property labels, log
  messages, exceptions) stays as received.
- **Changing or adding text means changing the catalogues in the same commit**: edit the
  English value, then the French one. When you can't translate well, still add the key to
  every language file (with the English text) so the parity test passes, and say so in the commit.
- **Plugins translate themselves.** Add `plugins/<id>/ui/locales/{en,fr}.json`; the loader in
  `ui/src/i18n.ts` picks them up, no core change. Two optional top-level keys are read by
  core: `label` (sidebar entry) and `manifest.name` / `manifest.description` (Options → Plugins).
- Non-React code (e.g. the store) uses `i18n.t(key, { ns })` — the result is fixed at call time.
- Keep copy free of implementation detail (see above) in *both* languages. A translation must not add or drop information.
- Numbers, RA/Dec and other astronomy formats keep their current notation (decimal point). Dates and
  times go through `Intl` with the active language.
- `cd ui && npm run lint` (ESLint, `eslint-plugin-i18next` `no-literal-string`) fails on literal text in
  JSX, in core and plugin UI alike. Units, glyphs and the product name are allow-listed in
  `ui/eslint.config.js`; add to that list for new symbols, never silence the rule on real copy.
  It checks JSX text only (not `title=`/`placeholder=` attributes), so translate those by hand.
- `tests/unit/test_ui_locales.py` checks every language file has exactly the English keys and the same
  `{{placeholders}}`/tags; `tests/unit/test_ui_translation_keys.py` checks every literal `t('key')` exists.
  Both run in the normal unit suite.

### Backend logging

Use `structlog` throughout. Get a logger at module level and log with structured key-value pairs:

```python
import structlog
logger = structlog.get_logger()

logger.info("my_feature.step_started", step=3, position=12450)
logger.warning("my_feature.no_stars", threshold=13.0)
logger.error("my_feature.failed", error=str(exc), exc_info=True)
```

Event names follow the `<plugin>.<verb>_<noun>` convention (matches WebSocket event types).
`exc_info=True` on errors ensures the full traceback lands in `astrolol.log` without cluttering
the console renderer.

### Log scopes (per-plugin verbosity control)

Declare `log_scopes` in the plugin's `PluginManifest` so users can toggle debug verbosity per
component from the Logs page gear menu at runtime:

```python
from astrolol.core.plugin_api import LogScope, PluginManifest

manifest = PluginManifest(
    id="my_feature",
    name="My Feature",
    ...
    log_scopes=[
        LogScope(key="my_feature", label="My Feature", logger="plugins.my_feature"),
    ],
)
```

- `key` — unique identifier, used by the UI toggle and the `POST /admin/log_level` endpoint.
- `label` — human-readable name shown in the Verbosity panel.
- `logger` — stdlib logger name whose level is toggled. Follows Python's logger hierarchy:
  setting `plugins.my_feature` to `DEBUG` covers `plugins.my_feature.client`,
  `plugins.my_feature.engine`, etc.

The core always registers scopes for `indi`, `device`, `mount`, `imager`, and `focuser`.
Plugin scopes are collected at startup and exposed via `GET /admin/log_scopes`;
`POST /admin/log_level` changes the live level without a restart.

## Testing requirements

**Every new feature that can be tested must have tests. No exceptions.**

- Plugin API tests go in `plugins/<name>/tests/`. Run them with
  `python3 -m pytest plugins/ -v`.
- Unit tests go in `tests/unit/`. Use `FakeCamera`, `FakeMount`, `FakeFocuser` from
  `tests/conftest.py` — no hardware required.
- Integration tests go in `tests/integration/` and are skipped automatically when
  `indiserver` is not installed.
- Use `TestClient` (httpx) for API tests. Create a fresh `FastAPI()` per test — never share
  app state between tests.
- Structlog output is captured by pytest's log system, not `capsys`. Use
  `caplog.at_level(logging.WARNING, logger="<module>")` to assert on log output.

Current count: **672 unit tests**, **37 integration tests**, **979 plugin tests** (all passing).

### UI unit tests

Pure UI logic (formatting, coordinate arithmetic, …) lives in plain `.ts` modules and is tested with
vitest: `cd ui && npm run test`. Put tests next to the module (`src/utils/dms.test.ts`). Keep logic
that needs testing out of components. There is no DOM test environment.

### TypeScript type checking

`ui/tsconfig.json` covers both `src/` and `plugins/**/*.tsx` — all plugin UI files are
type-checked alongside core UI. A pre-commit hook enforces this on every commit:

```bash
cd ui && npm run typecheck   # run manually; the pre-commit hook does this automatically
```

`vite-plugin-checker` also shows TypeScript errors as a browser overlay during `npm run dev`,
so type errors surface immediately without waiting for a build.

**Do not bypass the pre-commit hook** (`--no-verify`). If `tsc` reports an error, fix it.
Missing imports and wrong types that reach runtime are harder to debug than a failed hook.

## Key conventions

- **Everything async.** No blocking calls on the event loop. Use `asyncio.create_subprocess_exec`
  for subprocesses, async-compatible libraries throughout.
- **Every long-running task must be cancellable.** Wrap in `asyncio.Task`, handle
  `asyncio.CancelledError`, clean up hardware state on cancellation.
- **Device adapters own hardware failure.** Each adapter implements `ping()`. The watchdog
  (not yet built) calls it periodically and transitions device state without crashing the app.
- **Standard adapters are bundled; the pluggy interface is for extensibility.**
  INDI lives in `astrolol/devices/indi/`. Third-party adapters register via entry points.
- **Pydantic models for everything crossing a boundary** (API, events, device status).
  Never pass raw dicts between layers.
- **No module-level mutable state in plugins.** Store everything on `app.state` so each
  `TestClient` gets a clean slate.

## Running the app

```bash
# Install (dev deps required for tests)
pip install -e ".[dev]"

# Backend only
python3 -m astrolol.main          # API at http://localhost:8000
                                   # Docs at http://localhost:8000/docs

# UI dev server (hot reload, proxies to backend)
cd ui && npm install && npm run dev   # UI at http://localhost:5173

# Production (UI served from backend)
cd ui && npm run build
python3 -m astrolol.main           # everything at http://localhost:8000
```

## Running tests

```bash
# All tests (unit + plugin tests)
python3 -m pytest tests/ plugins/ -v

# Unit tests only (no hardware)
python3 -m pytest tests/unit/ -v

# Integration tests (require indiserver / indi-bin)
python3 -m pytest tests/integration/ -v

# TypeScript type checking (src/ + plugins/)
cd ui && npm run typecheck

# Lint: no untranslated text in JSX (src/ + plugins/)
cd ui && npm run lint
```

## Docker development environment

```bash
# Build and start all services
docker-compose up

# Run tests inside the container
docker-compose run --rm backend python3 -m pytest tests/ plugins/ -v
```

Backend API at `http://localhost:8000`, UI dev server at `http://localhost:80`.
Vite proxies `/api`, `/devices`, `/profiles`, `/imager`, `/mount`, `/focuser`, `/filter_wheel`,
`/indi`, `/inventory`, `/settings`, `/events`, `/health`, `/plugins`, `/admin`, and `/ws` to the
backend container. All plugin routes are mounted under `/plugins/<id>/...`, so no per-plugin
proxy entries are needed.

## Project structure

```
astrolol/
├── api/
│   ├── devices.py      # connect/disconnect endpoints
│   ├── focuser.py      # move_to, move_by, halt, status, per-device settings
│   ├── imager.py       # expose, loop, image serving
│   ├── mount.py        # slew, stop, park, sync, tracking, meridian_flip
│   ├── settings.py     # GET/PUT /settings (UserSettings)
│   └── static.py       # serves ui/dist/ in production
├── core/
│   ├── errors.py       # domain exception hierarchy
│   ├── plugin_api.py   # Plugin protocol, PluginManifest, PluginContext
│   ├── events/         # EventBus (asyncio pub/sub, ring buffer) + typed event models
│   ├── guiding/         # Guider Protocol + GuiderStatus/GuidingHealth/SettleParams models,
│   │                   # GuidingHealthTracker — shared contract for phd2 + guide_simulator
│   └── sequencer/       # Sequencer Protocol + task/session/lane event & model set —
│                        # the plugin-agnostic contract the sequencer plugin implements
├── devices/
│   ├── base/           # ICamera, IMount, IFocuser Protocols + Pydantic models; optional
│   │                   # IStreamingCamera (streaming.py: Frame, latest-wins subscriptions) and
│   │                   # IPulseGuider (pulse.py)
│   ├── config.py       # DeviceConfig — friendly ID generation + validation
│   ├── manager.py      # DeviceManager — connect/disconnect lifecycle + events
│   ├── registry.py     # DeviceRegistry — adapter_key → class mapping
│   └── indi/           # INDI adapters (camera, mount, focuser + IndiClient)
├── equipment/          # EquipmentStore — physical equipment tree (site/mount/OTA/camera/
│                       # filter wheel/focuser/rotator/GPS) as profile-node graph, OpticalPath
├── filter_wheel/
│   └── manager.py      # FilterWheelManager — move/status lifecycle
├── focuser/
│   └── manager.py      # FocuserManager — move tasks, halt, events
├── imaging/
│   ├── imager.py       # ImagerManager — per-camera expose/loop tasks
│   ├── models.py       # ExposureRequest, ExposureResult, ImagerState
│   └── preview.py      # FITS → JPEG (percentile auto-stretch, astropy + Pillow)
├── mount/
│   └── manager.py      # MountManager — slew/park/flip tasks, sync, tracking, events
├── persistence/        # empty stub — planned SQLAlchemy/aiosqlite/Alembic layer, not started
├── config/
│   ├── logging_setup.py  # structlog config + EventBusForwarder (log → EventBus bridge)
│   ├── settings.py       # pydantic-settings (images_dir, jpeg_quality, ASTROLOL_ prefix)
│   └── user_settings.py  # UserSettings (save templates, enabled_plugins) + store
├── profiles/
│   ├── models.py       # Profile, ProfileDevice
│   └── store.py        # ProfileStore — JSON persistence, last-active tracking
├── app.py              # pluggy device-adapter wiring + plugin discovery/setup
├── main.py             # FastAPI app factory, lifespan, /health, /plugins, /admin/restart
└── plugin.py           # pluggy hookspec (register_devices)

plugins/
├── hello/              # Minimal full-stack plugin (PoC / reference implementation)
├── autofocus/          # Full-stack plugin — canonical example for complex plugins
├── eqmod/              # Native (non-INDI) Sky-Watcher motor-controller driver: GoTo/sync/
│                       # tracking/park over EQMOD cable or USB; ships an INDI mount-proxy so
│                       # PHD2/other INDI clients can guide through it
├── guider/             # Built-in autoguider (REST API + UI page, first version): star detection,
│                       # dark frames, windowed tracking, calibration (pulse→pixel matrix),
│                       # controller, BuiltinGuider implementing core.guiding.Guider.
│                       # Frames come from IStreamingCamera, pulses go to IPulseGuider on the
│                       # guide camera (ST4) or the mount — selectable, camera by default
├── guide_simulator/    # Simulated guider (registers against core/guiding) for testing
│                       # without PHD2/hardware — noisy steps, settling, injectable faults
├── lx200/              # Virtual LX200 telescope TCP server (SkySafari, Cartes du Ciel, etc.)
├── mdns/               # Advertises this server via mDNS (_astrolol._tcp.local.) so clients
│                       # can find it without a typed-in IP; advertised host/port/scheme are
│                       # explicit settings since astrolol can't know what a reverse proxy
│                       # in front of it exposes
├── object_resolver/    # Offline-first name → J2000 coords resolver (NGC/IC/Messier/
│                       # Sharpless/Hipparcos + common names), SIMBAD fallback, solar system
├── phd2/               # PHD2 autoguider client — implements core.guiding.Guider, guide
│                       # graph, auto-dither, health check
├── platesolve/         # ASTAP-backed astrometric solving + solve-sync-reslew loop
├── sequencer/          # Task-queue imaging sequencer — ordered exposure plans with slew/
│                       # center/guide/dither/meridian-flip, resumable, multi-camera lanes,
│                       # session journal, named/saved sequences. Largest plugin.
├── stellarium/         # Stellarium "remote telescope" TCP protocol server (same pattern
│                       # as lx200)
├── system/             # Host-machine management — WiFi/AP mode, system info, thermal/
│                       # power throttle monitoring
└── target/             # Object search UI (uses object_resolver), rise/set/transit +
                         # altitude graph, sets mount target, favourites

# Each plugin follows the same layout: plugin.py, api.py, optional engine/protocol modules,
# ui/ (index.ts + page + optional chip + api.ts), tests/. See plugins/hello/ for the minimal
# shape and plugins/sequencer/ for the largest (runner.py, lanes.py, journal.py, sequences.py,
# stalls.py, targets.py, focusing.py, guiding.py, devices.py; 8 test files, 12 UI files).

ui/
├── src/
│   ├── api/            # typed fetch client (core devices only) + hand-written types
│   ├── hooks/          # useEvents (WebSocket), useLocalStorage
│   ├── i18n.ts         # i18next setup; loads core + plugin catalogues
│   ├── locales/        # core catalogues: <lng>/<namespace>.json
│   ├── utils/          # formatting.ts — fmtRA, fmtDec
│   ├── store/          # Zustand — core device state + pluginStates + registerPluginEventHandlers
│   ├── plugin-registry.ts  # runtime map: plugin id → { route, icon, Component, StatusChip? }
│   ├── components/
│   │   └── ui/         # EventLog, PillGroup, DurationStepper, Input, ToggleSwitch,
│   │                   # Card, SidebarSection, Badge, Chip, StatusPill, Button
│   └── pages/          # Equipment, Profiles, Imaging, Mount, Logs, Options
└── vite.config.ts      # @plugins alias + vite-plugin-checker + proxy

tests/
├── conftest.py         # FakeCamera (real FITS), FakeMount, FakeFocuser + fixtures
├── unit/               # 672 tests — no hardware required
└── integration/        # 37 tests — require indiserver (skipped if not installed)
```

## Deferred work

See `TODO.md` for the full backlog with priorities.
