# astrolol

Headless, modular, open-source astronomy platform. Runs on the machine attached to your
telescope (Raspberry Pi, mini-PC, etc.). Connect from any web browser.

## What works today

- **Device management** — connect cameras, mounts, and focusers via INDI. Standard adapters
  are bundled; third-party adapters install as packages via the pluggy entry-point system.
- **Equipment profiles** — named device configurations persisted to JSON. Activate a profile
  to reconnect all devices automatically at startup.
- **Imager** — single exposures and continuous loops per camera. FITS files stored server-side,
  auto-stretched JPEG preview streamed to clients.
- **Mount control** — slew, stop, park/unpark, sync, tracking on/off (sidereal/lunar/solar).
  Pier side, hour angle, and meridian-flip button shown when |HA| ≤ 1 h.
- **Focuser control** — absolute and relative moves, halt.
- **Live event stream** — all state changes broadcast to connected clients over WebSocket,
  with a ring-buffer replay for late-joining clients.
- **Plugin system** — self-contained feature plugins in `plugins/`. Each plugin registers its
  own API routes, UI page, and sidebar entry. Enable/disable from Options with a live restart.
- **Web UI** — dark-theme React app: Equipment, Profiles, Imaging, Mount, Logs, Options pages,
  plus one page per enabled plugin.

## Requirements

- Python 3.11+
- Node.js 18+ (for the web UI)
- Linux (Raspberry Pi, mini-PC, or any machine at the scope)
- Optional: `indi-bin` package for INDI simulator integration tests

## Install

```bash
git clone https://github.com/you/astrolol
cd astrolol
pip install -e ".[dev]"   # [dev] includes pytest, pytest-asyncio, httpx, etc.
cd ui && npm install
```

## Run

**Development** (hot-reloading UI):
```bash
# terminal 1
python3 -m astrolol.main

# terminal 2
cd ui && npm run dev
# open http://localhost:5173
```

**Production** (everything from one port):
```bash
cd ui && npm run build
python3 -m astrolol.main
# open http://localhost:8000
```

API docs: `http://localhost:8000/docs`

## Docker

```bash
docker-compose up
# backend at http://localhost:8000, UI dev server at http://localhost:80
```

Source is bind-mounted; code changes are live without rebuild. Rebuild only when
`pyproject.toml` or `ui/package.json` change.

## Test

```bash
python3 -m pytest tests/ plugins/ -v
```

191 unit tests require no hardware. 34 integration tests (in `tests/integration/`) require
`indiserver` and are skipped automatically when it is not installed.

## Adding features

New features should live in `plugins/` whenever possible — self-contained directory with
its own API, UI component, and tests. See `plugins/hello/` for a minimal example.

Core changes (device adapters, event bus, profile store, etc.) go in `astrolol/`.

**Every new feature that can be tested must have tests.** Untested code in a PR will be
sent back.
