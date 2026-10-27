# astrolol user guide

astrolol runs on a small computer attached to your telescope (a Raspberry Pi, a mini-PC, a
laptop) and controls the mount, cameras, focuser and filter wheel. You use it from a web browser
on any phone, tablet or computer on the same network. Several people can watch the same session
at once; what one of them does is shown live to everyone.

![astrolol on a phone](../images/mobile.jpeg)

## Start here

1. [Installing astrolol](install.md) on the telescope computer.
2. [Getting started](getting-started.md): open astrolol, connect your first device, build your
   inventory, create a profile.
3. [The interface](interface.md): menu, status bar, palettes, languages, using a phone.

## Core screens

| Screen | What it is for |
|---|---|
| [Equipment](equipment.md) | Connect devices and keep the inventory of everything you own |
| [Profiles](profiles.md) | Describe a rig as an equipment tree and connect it in one click |
| [Imaging](imaging.md) | One page per camera: expose, loop, cool, focus, change filters |
| [Mount](mount.md) | Position, GoTo, sync, tracking, park, meridian and horizon limits, nudge |
| [Logs](logs.md) | Everything that happened, with per-component verbosity |
| [Dock](dock.md) | Side panel that keeps a few read-outs in view on every page |
| [Options](options.md) | Language, palette, where images are saved, INDI server, plugins |

## Features (plugins)

Most features are plugins. They are off until you turn them on in
[Options → Plugins](options.md#plugins) and restart astrolol.

**Observing**

| Page | What it is for |
|---|---|
| [Target](../../astrolol/plugins/target/docs/en.md) | Find an object, see when it is visible, point the mount at it, keep favourites |
| [Plate Solving](../../astrolol/plugins/platesolve/docs/en.md) | Find out where the telescope really points, sync and re-centre |
| [Polar Align](../../astrolol/plugins/polar_align/docs/en.md) | Polar scope reticle and a three-point plate-solve alignment |
| [Autofocus](../../astrolol/plugins/autofocus/docs/en.md) | Find the best focus with a V-curve |
| [Guider](../../astrolol/plugins/guider/docs/en.md) | The built-in autoguider |
| [PHD2 Guiding](../../astrolol/plugins/phd2/docs/en.md) | Use PHD2 as the guider |
| [Sequencer](../../astrolol/plugins/sequencer/docs/en.md) | Plan a night: targets, exposures, guiding, dithering, flips, journal |
| [Flat Wizard](../../astrolol/plugins/flat_wizard/docs/en.md) | Find the right flat exposure for each filter and queue the flats |
| [Viewer](../../astrolol/plugins/viewer/docs/en.md) | Browse every frame you captured |

**Equipment**

| Page | What it is for |
|---|---|
| [EQMOD](../../astrolol/plugins/eqmod/docs/en.md) | Native driver for Sky-Watcher mounts |
| [Bluetooth Serial](../../astrolol/plugins/bluetooth_serial/docs/en.md) | Pair a Bluetooth serial adapter (e.g. a wireless EQMOD cable) |
| [Stellarium Server](../../astrolol/plugins/stellarium/docs/en.md) | Follow and drive the mount from Stellarium |
| [LX200 Server](../../astrolol/plugins/lx200/docs/en.md) | Follow and drive the mount from SkySafari, Cartes du Ciel and other planetarium programs |
| [Guide Simulator](../../astrolol/plugins/guide_simulator/docs/en.md) | A pretend guider to rehearse without hardware |

**Settings**

| Page | What it is for |
|---|---|
| [Security](../../astrolol/plugins/security/docs/en.md) | Accounts, guest access, API tokens |
| [System](../../astrolol/plugins/system/docs/en.md) | Wi-Fi and hotspot, temperature, power, time zone, reboot |
| [mDNS](../../astrolol/plugins/mdns/docs/en.md) | Let apps find astrolol on the local network |
| [AI assistants](../../astrolol/plugins/mcp/docs/en.md) | Let Claude and other AI assistants look at and operate the rig |

## Installing

[Installing astrolol](install.md) covers the package for Debian, Raspberry Pi OS and Ubuntu,
with HTTPS. To run it from source code instead, see the
[Raspberry Pi deployment guide](../raspberry-pi-deployment.md).
