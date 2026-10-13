# EQMOD

*Plugin: EQMOD Mount.* A driver for Sky-Watcher mounts (EQ5, HEQ5, EQ6, AZ-EQ6, EQ8…) built
into astrolol. It connects through an EQMOD cable, the mount's own USB port, or a Bluetooth
adapter, and also includes a mount simulator.

## Connecting the mount

In [Equipment](../../../../docs/en/equipment.md), **Load driver** → **Mount** → **Other adapter** → `eqmod`, with
connect params such as:

```json
{"port": "/dev/ttyUSB0"}
```

Optional params:

- `"baudrate"`: skip speed detection (9600 for an EQMOD cable, 115200 for the AZ-EQ6's
  built-in USB).
- `"ra_reverse"` / `"dec_reverse"`: `true` if a nudge moves the mount the wrong way.
- `"guide_rate"`: guiding speed as a fraction of sidereal (0.5 by default).

To try it without a mount, choose the simulator adapter (`eqmod_sim`).

Then import it into the inventory and add it to your profile. The site from the profile gives
the mount its location; the meridian and horizon limits are set on the [Mount](../../../../docs/en/mount.md) page.

## The EQMOD page

With the mount connected, the page shows what the motor controller reports: port and speed,
board version, tracking state, guide rate, meridian limit and how far the mount is from it, the
site, the park position and the sync offset. Each axis shows its position in counts and degrees
from home and its state (*running*, *blocked*…). Useful when something does not move as
expected.

## Settings

- **Polar scope LED**: brightness of the polar scope illumination, on mounts that have one.
- **INDI mount proxy**: makes the mount visible to INDI programs, as *astrolol Mount Proxy* on
  astrolol's INDI server (port 7624).
  - **PHD2**: connect to the INDI server on the telescope computer, pick your INDI guide camera
    and *astrolol Mount Proxy* as the mount.
  - INDI drivers that read the telescope position (for FITS headers, or the CCD simulator's
    star field): set their telescope to *astrolol Mount Proxy*.

## Connect over Bluetooth

For a Bluetooth adapter in place of the cable: pair it first on the
[Bluetooth Serial](../../bluetooth_serial/docs/en.md) page, then here pick it and click **Apply** for your
EQMOD mount. Reconnect the mount (or reload the profile) for it to take effect.
