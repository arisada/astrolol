# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Headless, async, modular Python astronomy platform. Think AsiAir but open source.
Runs on a machine attached to the telescope (e.g. Raspberry Pi). Clients (web, mobile, native)
connect via REST and WebSocket. The backend owns all state — clients are observers.

## Architecture in one paragraph

FastAPI serves the REST and WebSocket API. Devices (camera, mount, focuser) are abstracted
behind `Protocol` interfaces in `astrolol/devices/base/`. Concrete adapters register themselves
via the pluggy plugin system at startup. Standard adapters (INDI) are **bundled inside astrolol**
in `astrolol/devices/indi/` — the pluggy interface exists for extensibility (ASCOM, direct
serial, etc.), not to force a separate install for the common case. An internal `EventBus`
(asyncio queues) lets any component publish typed events; connected WebSocket clients subscribe
and receive a live JSON stream. A React + TypeScript web UI is served as static files from
`ui/dist/` and proxied through Vite in development.

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

### Status-bar chips

If a plugin has activity worth surfacing globally (an ongoing run, a background task), export a
`StatusChip` component from `index.ts`. The `StatusBar` renders all plugin chips automatically —
no changes to `StatusBar.tsx` are needed.

The chip is responsible for its own full rendering, including deciding when to return `null`
(when the plugin is idle). Keep chips compact: a label, a separator dot, and a short status
string. Use the inline Tailwind classes from the existing chips as a reference for consistent
colouring:

```tsx
// bg-amber-500/20 text-amber-300 border-amber-500/30   ← in-progress / moving
// bg-emerald-500/20 text-emerald-300 border-emerald-500/30  ← done / tracking
// bg-sky-500/20 text-sky-300 border-sky-500/30         ← exposing / busy
// bg-violet-500/20 text-violet-300 border-violet-500/30← solving / computing
// bg-slate-700/50 text-slate-400 border-slate-600/40   ← idle / connected
```

Add `animate-pulse` for states that are actively progressing.

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

Current count: **263 unit tests**, **34 integration tests** (all passing).

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
```

## Docker development environment

```bash
# Build and start all services
docker-compose up

# Run tests inside the container
docker-compose run --rm backend python3 -m pytest tests/ plugins/ -v
```

Backend API at `http://localhost:8000`, UI dev server at `http://localhost:80`.
Vite proxies `/devices`, `/imager`, `/mount`, `/focuser`, `/ws`, `/plugins`, `/hello`,
`/admin` to the backend container.

## Project structure

```
astrolol/
├── api/
│   ├── devices.py      # connect/disconnect endpoints
│   ├── focuser.py      # move_to, move_by, halt, status
│   ├── imager.py       # expose, loop, image serving
│   ├── mount.py        # slew, stop, park, sync, tracking, meridian_flip
│   ├── settings.py     # GET/PUT /settings (UserSettings)
│   └── static.py       # serves ui/dist/ in production
├── core/
│   ├── errors.py       # domain exception hierarchy
│   ├── plugin_api.py   # Plugin protocol, PluginManifest, PluginContext
│   └── events/         # EventBus (asyncio pub/sub, ring buffer) + typed event models
├── devices/
│   ├── base/           # ICamera, IMount, IFocuser Protocols + Pydantic models
│   ├── config.py       # DeviceConfig — friendly ID generation + validation
│   ├── manager.py      # DeviceManager — connect/disconnect lifecycle + events
│   ├── registry.py     # DeviceRegistry — adapter_key → class mapping
│   └── indi/           # INDI adapters (camera, mount, focuser + IndiClient)
├── focuser/
│   └── manager.py      # FocuserManager — move tasks, halt, events
├── imaging/
│   ├── imager.py       # ImagerManager — per-camera expose/loop tasks
│   ├── models.py       # ExposureRequest, ExposureResult, ImagerState
│   └── preview.py      # FITS → JPEG (percentile auto-stretch, astropy + Pillow)
├── mount/
│   └── manager.py      # MountManager — slew/park/flip tasks, sync, tracking, events
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
│   ├── plugin.py       # HelloPlugin — setup() registers router, initialises app.state
│   ├── api.py          # GET/POST /hello/property, structlog instrumented
│   ├── ui/
│   │   └── HelloPage.tsx
│   └── tests/
│       └── test_hello_api.py   # 8 tests
└── autofocus/          # Full-stack plugin — canonical example for complex plugins
    ├── plugin.py
    ├── api.py          # /start /abort /run /run/preview/{step} /settings
    ├── engine.py       # async autofocus run orchestration
    ├── star_detector.py
    ├── algorithms.py   # parabola + hyperbola curve fitting
    ├── models.py       # AutofocusRun, FocusDataPoint, CurveFit, events
    ├── ui/
    │   ├── index.ts        # registers event handlers + exports StatusChip
    │   ├── AutofocusPage.tsx
    │   ├── AutofocusChip.tsx  # status-bar chip, reads pluginStates['autofocus']
    │   └── api.ts          # plugin-local fetch helpers
    └── tests/
        └── test_autofocus_api.py

ui/
├── src/
│   ├── api/            # typed fetch client (core devices only) + hand-written types
│   ├── hooks/          # useEvents — WebSocket with auto-reconnect
│   ├── store/          # Zustand — core device state + pluginStates + registerPluginEventHandlers
│   ├── plugin-registry.ts  # runtime map: plugin id → { route, icon, Component, StatusChip? }
│   ├── components/     # Layout, Sidebar, StatusBar (auto-renders plugin StatusChips), base UI
│   └── pages/          # Equipment, Profiles, Imaging, Mount, Logs, Options
└── vite.config.ts      # @plugins alias + proxy for /devices /imager /mount etc.

tests/
├── conftest.py         # FakeCamera (real FITS), FakeMount, FakeFocuser + fixtures
├── unit/               # 191 tests — no hardware required
└── integration/        # 34 tests — require indiserver (skipped if not installed)
```

## Deferred work

See `TODO.md` for the full backlog with priorities.
