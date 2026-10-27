# astrolol

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Headless, modular, open-source astronomy platform. Runs on the machine attached to your
telescope (Raspberry Pi, mini-PC, etc.). Connect from any web browser.

Source: https://github.com/arisada/astrolol

## What works today

- **Device management** — connect cameras, mounts, focusers, and filter wheels via INDI.
  Standard adapters are bundled; third-party adapters install as packages via the pluggy
  entry-point system. `astrolol/plugins/eqmod/` adds a native (non-INDI) serial driver for Sky-Watcher
  motor controllers, with an INDI proxy so INDI-only clients can still guide through it.
- **Equipment profiles** — named device configurations persisted to JSON, plus a separate
  equipment tree (site/mount/OTA/camera/filter wheel/focuser/rotator/GPS) for describing your
  physical setup. Activate a profile to reconnect all devices automatically at startup.
- **Imager** — single exposures and continuous loops per camera. FITS files stored server-side,
  auto-stretched JPEG preview streamed to clients.
- **Mount control** — slew, stop, park/unpark, sync, tracking on/off (sidereal/lunar/solar).
  Pier side, hour angle, meridian-flip, directional nudge. Coordinates displayed in ICRS (J2000)
  or JNow.
- **Focuser control** — absolute and relative moves, halt. Autofocus plugin with parabola/
  hyperbola curve fitting (field accuracy not yet verified — see `TODO.md`).
- **Target search** — resolve object names (NGC/IC/Messier/Sharpless/Hipparcos catalogs, common
  names, planets) to J2000 coordinates offline, with SIMBAD fallback; rise/set/transit and an
  altitude graph; favourites; sets the mount's target.
- **Plate solving** — ASTAP integration (async, cancellable). Sync-and-re-slew workflow:
  solve, sync mount, set target, slew.
- **Guiding** — a guider-agnostic core contract (`astrolol/core/guiding/`) implemented by a
  PHD2 client (connect to a running instance, start/stop guiding, dithering, live RMS display)
  and a guide simulator for testing without hardware.
- **Sequencer** — task-queue imaging automation: ordered exposure plans with slew/center/guide/
  dither/meridian-flip steps, resumable runs, multi-camera lanes, a session journal, and
  named/saved sequences with task-file import/export.
- **Telescope-protocol servers** — LX200 and Stellarium "remote telescope" TCP servers so
  planetarium apps (SkySafari, Cartes du Ciel, Stellarium, TheSkyX, Voyager, …) can track the
  mount astrolol controls.
- **System management** — WiFi connect/AP-mode switching, system info, and thermal/power
  throttle monitoring for the host machine (e.g. a Raspberry Pi).
- **Security** — optional sign-in with read-only, operator and admin users, guest access, API tokens
  for other tools and configurable allowed origins (see [Security](#security)).
- **Live event stream** — all state changes broadcast to connected clients over WebSocket,
  with a ring-buffer replay for late-joining clients.
- **Plugin system** — self-contained feature plugins in `astrolol/plugins/`. Each plugin registers its
  own API routes, UI page, and sidebar entry. Enable/disable from Options with a live restart.
- **Web UI** — dark-theme React app: Equipment, Profiles, Imaging, Mount, Focuser, Logs,
  Options pages, plus one page per enabled plugin.

Pre-1.0: functional core with a wide plugin surface, but persistence beyond JSON files, a
red-mode/mobile UI, and a packaged install (systemd and nginx files are in `deploy/`) are not
finished yet — see `TODO.md`.

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

**Optional: INDIGO instead of INDI**

astrolol can drive an [INDIGO](https://www.indigo-astronomy.org) server instead of indiserver:
install INDIGO (Debian and Raspberry Pi OS: the `indigo3` package from
`https://indigo-astronomy.github.io/indigo_ppa/ppa`; elsewhere, build it from source) and choose
INDIGO in Options → INDI Server, or start astrolol with `ASTROLOL_INDI_SERVER_KIND=indigo`. Set
`ASTROLOL_INDIGO_SERVER_PATH` (or the INDIGO server program in Options) if `indigo_server` is not
on the `PATH`. The Equipment page then lists INDIGO's drivers.

**Optional: ASCOM Alpaca devices**

Nothing to install: enable the ASCOM Alpaca plugin (Options → Plugins) and it finds Alpaca
devices (built-in Alpaca, ASCOM Remote) on the network. For tests without hardware, ASCOM's
[OmniSim](https://github.com/ASCOMInitiative/ASCOM.Alpaca.Simulators/releases) simulators have
self-contained Linux builds (x64, armhf, aarch64): unpack one and put `ascom.alpaca.simulators`
on the `PATH`.

**Optional: ASTAP plate solver, gsc**

```bash
sudo apt-get install astap-cli gsc
```

**Optional: Bluetooth serial devices** (`bluetooth_serial` plugin):
```bash
sudo apt-get install bluez bluez-tools
```
The user running astrolol needs D-Bus access to `org.bluez` (normally granted
via membership in the `bluetooth` group).

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

## Configuration

What you change in the UI is saved in the data directory. A few start-up settings are read
once, when astrolol starts, from (highest priority first):

1. environment variables, `ASTROLOL_<SETTING>` (e.g. `ASTROLOL_INDI_PORT=7625`),
2. the configuration file `/etc/astrolol/astrolol.toml`, if it exists (`ASTROLOL_CONFIG` names
   another file),
3. the defaults.

```toml
# /etc/astrolol/astrolol.toml
data_dir = "/var/lib/astrolol"      # settings, profiles, users, logs. Default: ~/.astrolol
images_dir = "/mnt/usb/raw"         # raw camera files. Default: <data_dir>/images
# ui_dist = "/path/to/ui/dist"      # the built web UI, if it is not found next to the code
# indi_server_kind = "indigo"       # also indi_manage_server, indi_host, indi_port,
                                    # indigo_server_path: then greyed out in Options
# allowed_origins = ["https://astro.example"]
```

The full list is `Settings` in [`astrolol/config/settings.py`](astrolol/config/settings.py). A
misspelt setting in the file stops astrolol at start, with the name in the error.

## Docker

```bash
docker-compose up
# backend at http://localhost:8000, UI dev server at http://localhost:80
```

Source is bind-mounted; code changes are live without rebuild. Rebuild only when
`pyproject.toml` or `ui/package.json` change.

## Test

```bash
python3 -m pytest tests/ astrolol/plugins/ -v
```

The real-time guiding tests (about 7 minutes) are skipped by default; run them with
`python3 -m pytest -m slow tests/integration/test_indi_guiding.py` before a release or after guiding
changes. Unit tests require no hardware. Integration tests (in `tests/integration/`) require
`indiserver` and are skipped automatically when it is not installed.

## Adding features

New features should live in `astrolol/plugins/` whenever possible — self-contained directory with
its own API, UI component, and tests. See `astrolol/plugins/hello/` for a minimal example.

Core changes (device adapters, event bus, profile store, etc.) go in `astrolol/`.

**Every new feature that can be tested must have tests.** Untested code in a PR will be
sent back.

## Security

**Out of the box astrolol has no authentication.** Anyone who can reach the web server can
control your telescope, start exposures, and read FITS images from disk. astrolol allows
setting paths to helper binaries from its web interface, which is a known security risk.

Enable the **Security** plugin (Options → Plugins, then restart) and create the first account
on its page to turn sign-in on:

- **Three access levels.** *Read-only* users observe every screen but change nothing;
  *operators* run the telescope, exposures and sequences; *admins* also change settings,
  plugins, equipment, users and tokens.
- **Guest access** (optional) lets people look without a password, as read-only.
- **API tokens** let other tools call the REST API without a password.
- **Allowed origins** list the web apps on other sites that may call the API with a token.
- Lost the admin password? On the Pi, run `python -m astrolol.plugins.security set-password
  <name>` (or `add-admin <name>`, or `reset` to go back to an open API) and restart astrolol.

Whether the plugin is on or off, a web page on another site can never drive astrolol through
your browser: requests from a different origin are refused.

Limits to know about:

- Use **HTTPS** (see the [deployment guide](docs/raspberry-pi-deployment.md)). Over plain HTTP
  a password and the session cookie can be read by anyone on the network; the UI warns you.
- The LX200, Stellarium and INDI listeners are separate network ports and are **not**
  covered by sign-in.
- Disabling the plugin opens the API again.

Either way:

- Run it on a **trusted local network only** (your home LAN, a dedicated AP at the
  observing site, or a VPN).
- Do **not** expose port 8000 directly to the internet or to untrusted Wi-Fi networks.
