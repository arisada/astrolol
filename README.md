# astrolol

Headless, modular, open-source astronomy platform. Runs on the machine attached to your
telescope (Raspberry Pi, mini-PC, etc.). Connect from any web browser.

Source: https://github.com/arisada/astrolol

## What works today

- **Device management** — connect cameras, mounts, and focusers via INDI. Standard adapters
  are bundled; third-party adapters install as packages via the pluggy entry-point system.
- **Equipment profiles** — named device configurations persisted to JSON. Activate a profile
  to reconnect all devices automatically at startup.
- **Imager** — single exposures and continuous loops per camera. FITS files stored server-side,
  auto-stretched JPEG preview streamed to clients.
- **Mount control** — slew, stop, park/unpark, sync, tracking on/off (sidereal/lunar/solar).
  Pier side, hour angle, meridian-flip, directional nudge. Coordinates displayed in ICRS (J2000)
  or JNow. Target concept: set a target independently of slewing, used by plate-solve sync and
  future sequencer.
- **Focuser control** — absolute and relative moves, halt.
- **Plate solving** — ASTAP integration (async, cancellable). Sync-and-re-slew workflow:
  solve, sync mount, set target, slew.
- **PHD2 guiding** — connect to a running PHD2 instance, start/stop guiding, dithering,
  live RMS display.
- **Live event stream** — all state changes broadcast to connected clients over WebSocket,
  with a ring-buffer replay for late-joining clients.
- **Plugin system** — self-contained feature plugins in `plugins/`. Each plugin registers its
  own API routes, UI page, and sidebar entry. Enable/disable from Options with a live restart.
- **Web UI** — dark-theme React app: Equipment, Profiles, Imaging, Mount, Focuser, Logs,
  Options pages, plus one page per enabled plugin.

## Requirements

- Python 3.11+
- Node.js 18+ (for the web UI)
- Linux (Raspberry Pi, mini-PC, or any machine at the scope)

**Optional: Install astroberry (rpi only)**

```bash
curl -fsSL https://astroberry.io/debian/astroberry.asc | sudo gpg --dearmor -o /etc/apt/keyrings/astroberry.gpg
curl -fsSL https://astroberry.io/debian/astroberry.sources | sudo tee /etc/apt/sources.list.d/astroberry.sources
sudo apt-get update
```

**INDI drivers** (required for real hardware and integration tests):
```bash
sudo apt-get install indi-bin
```

**Nodejs and npm**
```bash
sudo apt-get install -y nodejs npm
```


**Optional: All indi drivers**

```bash
sudo apt-get install indi-full
```

**Optional: ASTAP plate solver, gsc**

```bash
sudo apt-get install astap-cli gsc
```

**Optional: PHD2 guiding**

astrolol can connect to local or remote PHD2 instances.

## Install

```bash
git clone https://github.com/arisada/astrolol
cd astrolol
pip install -e ".[dev]" --break-system-packages
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

Unit tests require no hardware. Integration tests (in `tests/integration/`) require
`indiserver` and are skipped automatically when it is not installed.

## Adding features

New features should live in `plugins/` whenever possible — self-contained directory with
its own API, UI component, and tests. See `plugins/hello/` for a minimal example.

Core changes (device adapters, event bus, profile store, etc.) go in `astrolol/`.

**Every new feature that can be tested must have tests.** Untested code in a PR will be
sent back.

## Security

**astrolol has no authentication.** Anyone who can reach the web server can control your
telescope, start exposures, and read FITS images from disk. astrolol allows setting paths to helper binaries from its web interface, which is a known security risk.

- Run it on a **trusted local network only** (your home LAN, a dedicated AP at the
  observing site, or a VPN).
- Do **not** expose port 8000 directly to the internet or to untrusted Wi-Fi networks.
- If you need remote access, put it behind a VPN such as WireGuard or an
  authenticating reverse proxy (nginx with `auth_basic`).
