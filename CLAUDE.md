# astrolol — developer notes for Claude

## What this is

Headless, async, modular Python astronomy platform. Think AsiAir but open source.
Runs on a machine attached to the telescope (e.g. Raspberry Pi). Clients (web, mobile, native)
connect via REST and WebSocket. The backend owns all state — clients are observers.

## Architecture in one paragraph

FastAPI serves the REST and WebSocket API. Devices (camera, mount, focuser) are abstracted
behind `Protocol` interfaces in `astrolol/devices/base/`. Concrete adapters register themselves
via the pluggy plugin system at startup. Standard adapters (INDI) are **bundled inside astrolol**
in `astrolol/devices/indi/` — the plugin interface exists for extensibility (ASCOM, direct
serial, etc.), not to force a separate install for the common case. An internal `EventBus`
(asyncio queues) lets any component publish typed events; connected WebSocket clients subscribe
and receive a live JSON stream. A React + TypeScript web UI is served as static files from
`ui/dist/` and proxied through Vite in development.

## Key conventions

- **Everything async.** No blocking calls on the event loop. Use `asyncio.create_subprocess_exec`
  for subprocesses, async-compatible libraries throughout.
- **Every long-running task must be cancellable.** Wrap in `asyncio.Task`, handle
  `asyncio.CancelledError`, clean up hardware state on cancellation.
- **Device adapters own hardware failure.** Each adapter implements `ping()`. The watchdog
  (not yet built) calls it periodically and transitions device state without crashing the app.
- **Standard adapters are bundled; the plugin interface is for extensibility.**
  INDI lives in `astrolol/devices/indi/`. Third-party adapters register via their own package's
  entry points — the mechanism is identical.
- **Pydantic models for everything crossing a boundary** (API, events, device status).
  Never pass raw dicts between layers.

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
python3 -m pytest tests/ -v
```

60 tests, all green. Fake device adapters (`FakeCamera`, `FakeMount`, `FakeFocuser`) in
`tests/conftest.py` — no hardware or INDI server required.

## Project structure

```
astrolol/
├── api/
│   ├── devices.py      # connect/disconnect endpoints
│   ├── focuser.py      # move_to, move_by, halt, status
│   ├── imager.py       # expose, loop, image serving
│   ├── mount.py        # slew, stop, park, sync, tracking
│   └── static.py       # serves ui/dist/ in production
├── core/
│   ├── errors.py       # domain exception hierarchy
│   └── events/         # EventBus (asyncio pub/sub) + typed event models
├── devices/
│   ├── base/           # ICamera, IMount, IFocuser Protocols + Pydantic models
│   ├── config.py       # DeviceConfig (kind + adapter_key + params)
│   ├── manager.py      # DeviceManager — connect/disconnect lifecycle + events
│   ├── registry.py     # DeviceRegistry — adapter_key → class mapping
│   └── indi/           # INDI adapters (to be implemented, bundled here)
├── focuser/
│   └── manager.py      # FocuserManager — move tasks, halt, events
├── imaging/
│   ├── imager.py       # ImagerManager — per-camera expose/loop tasks
│   ├── models.py       # ExposureRequest, ExposureResult, ImagerState
│   └── preview.py      # FITS → JPEG (percentile auto-stretch, astropy + Pillow)
├── mount/
│   └── manager.py      # MountManager — slew/park tasks, sync, tracking, events
├── config/
│   └── settings.py     # pydantic-settings (images_dir, jpeg_quality, ASTROLOL_ prefix)
├── persistence/        # future: SQLAlchemy + aiosqlite
├── app.py              # plugin manager + registry wiring
├── main.py             # FastAPI app factory + uvicorn entrypoint
└── plugin.py           # pluggy hookspec (register_devices)

ui/
├── src/
│   ├── api/            # typed fetch client + hand-written types (generate with npm run generate-api-types)
│   ├── hooks/          # useEvents — WebSocket connection with auto-reconnect
│   ├── store/          # Zustand — device list, latest image, focuser position, event log
│   ├── components/     # Layout, Sidebar, base UI components (Button, Input, StateBadge)
│   └── pages/          # Equipment, Imaging, Options
└── vite.config.ts      # proxies /devices /imager /mount /focuser /ws → backend in dev

tests/
├── conftest.py         # FakeCamera (writes real FITS), FakeMount, FakeFocuser + fixtures
└── unit/               # 60 tests — no hardware required
```

## Deferred work

See `TODO.md` for the full backlog with priorities.
