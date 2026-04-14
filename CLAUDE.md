# astrolol — developer notes for Claude

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
    │   └── MyPage.tsx     # React page, imported via @plugins alias
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
- See `plugins/hello/` for the canonical minimal example.

**Core code** (`astrolol/`) is for infrastructure: device adapters, event bus, profile store,
settings, API wiring. Features with UI, their own API routes, and optional enable/disable belong
in plugins.

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

Current count: **191 unit tests**, **34 integration tests** (all passing).

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
└── hello/              # Minimal full-stack plugin (PoC / reference implementation)
    ├── plugin.py       # HelloPlugin — setup() registers router, initialises app.state
    ├── api.py          # GET/POST /hello/property, structlog instrumented
    ├── ui/
    │   └── HelloPage.tsx
    └── tests/
        └── test_hello_api.py   # 8 tests

ui/
├── src/
│   ├── api/            # typed fetch client + hand-written types
│   ├── hooks/          # useEvents — WebSocket with auto-reconnect
│   ├── store/          # Zustand — devices, image, focuser, event log, pluginInfos
│   ├── plugin-registry.ts  # static map: plugin id → { route, icon, Component }
│   ├── components/     # Layout, Sidebar (renders plugin nav items), base UI
│   └── pages/          # Equipment, Profiles, Imaging, Mount, Logs, Options
└── vite.config.ts      # @plugins alias + proxy for /devices /imager /mount etc.

tests/
├── conftest.py         # FakeCamera (real FITS), FakeMount, FakeFocuser + fixtures
├── unit/               # 191 tests — no hardware required
└── integration/        # 34 tests — require indiserver (skipped if not installed)
```

## Deferred work

See `TODO.md` for the full backlog with priorities.
