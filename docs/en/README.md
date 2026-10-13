# astrolol user guide

astrolol runs on a small computer attached to your telescope (a Raspberry Pi, a mini-PC, a
laptop) and controls the mount, cameras, focuser and filter wheel. You use it from a web browser
on any phone, tablet or computer on the same network. Several people can watch the same session
at once; what one of them does is shown live to everyone.

![astrolol on a phone](../images/mobile.jpeg)

## Start here

1. [Getting started](getting-started.md): open astrolol, connect your first device, build your
   inventory, create a profile.
2. [The interface](interface.md): menu, status bar, palettes, languages, using a phone.

## Core screens

| Screen | What it is for |
|---|---|
| [Equipment](equipment.md) | Connect devices and keep the inventory of everything you own |
| [Profiles](profiles.md) | Describe a rig as an equipment tree and connect it in one click |
| [Imaging](imaging.md) | One page per camera: expose, loop, cool, focus, change filters |
| [Mount](mount.md) | Position, GoTo, sync, tracking, park, meridian and horizon limits, nudge |
| [Logs](logs.md) | Everything that happened, with per-component verbosity |
| [Options](options.md) | Language, palette, where images are saved, INDI server, plugins |

## Features (plugins)

Most features are plugins. They are off until you turn them on in
[Options → Plugins](options.md#plugins) and restart astrolol.

**Observing**

| Page | What it is for |
|---|---|
| [Target](target.md) | Find an object, see when it is visible, point the mount at it, keep favourites |
| [Plate Solving](platesolve.md) | Find out where the telescope really points, sync and re-centre |
| [Polar Align](polar-align.md) | Polar scope reticle and a three-point plate-solve alignment |
| [Autofocus](autofocus.md) | Find the best focus with a V-curve |
| [Guider](guider.md) | The built-in autoguider |
| [PHD2 Guiding](phd2.md) | Use PHD2 as the guider |
| [Sequencer](sequencer.md) | Plan a night: targets, exposures, guiding, dithering, flips, journal |
| [Flat Wizard](flat-wizard.md) | Find the right flat exposure for each filter and queue the flats |
| [Viewer](viewer.md) | Browse every frame you captured |

**Equipment**

| Page | What it is for |
|---|---|
| [EQMOD](eqmod.md) | Native driver for Sky-Watcher mounts |
| [Bluetooth Serial](bluetooth-serial.md) | Pair a Bluetooth serial adapter (e.g. a wireless EQMOD cable) |
| [Planetarium servers](planetarium.md) | Drive the mount from Stellarium, SkySafari, Cartes du Ciel… |
| [Guide Simulator](guide-simulator.md) | A pretend guider to rehearse without hardware |

**Settings**

| Page | What it is for |
|---|---|
| [Security](security.md) | Accounts, guest access, API tokens |
| [System](system.md) | Wi-Fi and hotspot, temperature, power, time zone, reboot |
| [mDNS](mdns.md) | Let apps find astrolol on the local network |

## Installing

Installing astrolol on the telescope computer is covered in the
[Raspberry Pi deployment guide](../raspberry-pi-deployment.md).
