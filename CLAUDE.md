# astrolol — developer notes for Claude

## What this is

Headless, async, modular Python astronomy platform. Think AsiAir but open source.
Runs on a machine attached to the telescope (e.g. Raspberry Pi). Clients (web, mobile, native)
connect via REST and WebSocket. The backend owns all state — clients are observers.

## Architecture in one paragraph

FastAPI serves the REST and WebSocket API. Devices (camera, mount, focuser) are abstracted
behind `Protocol` interfaces in `astrolol/devices/base/`. Concrete adapters (e.g. INDI) live in
separate installable packages (`astrolol-indi`) and register themselves via the pluggy plugin
system at startup. An internal `EventBus` (asyncio queues) lets any component publish typed
events; connected WebSocket clients subscribe and receive a live stream. SQLite (via
SQLAlchemy async) persists profiles and session history.

## Key conventions

- **Everything async.** No blocking calls on the event loop. Use `asyncio.create_subprocess_exec`
  for subprocesses, async SQLAlchemy for DB, async-compatible libraries throughout.
- **Every long-running task must be cancellable.** Wrap in `asyncio.Task`, handle
  `asyncio.CancelledError`, clean up hardware state on cancellation.
- **Device adapters own hardware failure.** Each adapter implements `ping()`. The watchdog
  (not yet built) calls it periodically and transitions device state without crashing the app.
- **Plugins register adapters, core knows nothing of INDI or any specific hardware.**
  The boundary: anything talking to physical hardware is a plugin.
- **Pydantic models for everything crossing a boundary** (API, events, device status).
  Never pass raw dicts between layers.

## Running the app

```bash
pip install -e ".[dev]"
python3 -m astrolol.main
# or
~/.local/bin/astrolol
```

## Running tests

```bash
python3 -m pytest tests/ -v
```

## Project structure

```
astrolol/
├── api/            # FastAPI routes (REST + WebSocket)
├── core/
│   ├── events/     # EventBus + event models
│   └── tasks/      # TaskManager (future)
├── devices/
│   ├── base/       # Protocol interfaces + Pydantic models
│   └── indi/       # INDI adapter (future, or separate package)
├── config/         # pydantic-settings config
└── persistence/    # SQLAlchemy models (future)
```

## Deferred work

See `TODO.md` for the full backlog with priorities.
