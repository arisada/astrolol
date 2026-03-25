# astrolol

Headless, modular, open-source astronomy platform. Runs on the machine attached to your
telescope. Connect from any web browser, mobile app, or native client.

> Built out of frustration with Windows-only and buggy alternatives. Named honestly.

## What works today

- **Device management** — connect cameras, mounts, and focusers via a plugin interface.
  Standard INDI adapters are bundled; third-party adapters install as packages.
- **Imager** — single exposures and continuous loops per camera, FITS stored server-side,
  auto-stretched JPEG preview streamed to clients.
- **Mount control** — slew, stop, park/unpark, sync, tracking on/off.
- **Focuser control** — absolute and relative moves, halt.
- **Live event stream** — all state changes broadcast to connected clients over WebSocket.
- **Web UI** — dark-theme React app with Equipment, Imaging, and Options pages.

## Requirements

- Python 3.11+
- Node.js 18+ (for the web UI)
- Linux (Raspberry Pi, mini-PC, or any machine at the scope)

## Install

```bash
git clone https://github.com/you/astrolol
cd astrolol
pip install -e ".[dev]"   # [dev] is required — includes pytest, pytest-asyncio, etc.
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

## Test

```bash
python3 -m pytest tests/ -v
```

No hardware or INDI server required — fake device adapters cover all test cases.

## Status

Early development. INDI adapters not yet implemented — the platform runs against
simulators and fake devices only. Not ready for use at the telescope.
