# Options

Settings that apply to the whole application. They are kept on the server, so every browser
sees the same.

## Language

**Interface language**: English or French.

## Palette

**Colour palette**: *Midnight* (default), *Atlas*, *Graphite*, *Void*, *Nebula*, *Mono*,
*Ember*, and two palettes for use at the telescope that keep your night vision: *Night red*
and *Night crimson*.

## Image Saving

Where and under which name frames are saved when *Save subs* is on (on the
[Imaging](imaging.md) page) and by the [Sequencer](sequencer.md).

- **Save directory**: a folder template. Default: `~/astrolol_pictures/%D` (one folder per
  date).
- **Filename template**: without extension; `.fits` is added. Default: `%F_%N_%Es_%Gg`.

An **Example** shows what the current templates produce. Click **Show token reference** for
the list:

| Token | Replaced by |
|---|---|
| `%D` | Date (YYYY-MM-DD) |
| `%T` | Time (HHMMSS) |
| `%U` | Home directory |
| `%O` | Object / target name |
| `%F` | Frame type (light/dark/flat/bias) |
| `%N` | Counter (6 digits, per camera) |
| `%C` | Camera name (device ID) |
| `%f` | Filter name (empty without a filter wheel) |
| `%E` | Exposure time (seconds) |
| `%G` | Gain |

For example `%U/astro/%O/%D` with `%F_%f_%Es_%N` gives
`/home/me/astro/M 31/2026-10-13/light_Ha_300s_000042.fits`.

## INDI Server

- **Manage indiserver automatically**: astrolol starts and stops the INDI server as devices are
  connected. Leave it on unless you run your own INDI server; in that case turn it off and set
  **INDI server host** and **port** (default 7624) under *Show advanced settings*.
- **Run directory**: where the INDI server keeps its control files.
- **Local image transfer**: the driver writes images straight to disk instead of sending them
  over the network connection. Faster, especially with large sensors. **Upload directory** is
  where the driver writes them.
- **INDI protocol logging**: *Off*, *Tags only* or *Full XML*. Records the traffic with the
  drivers in the [log](logs.md). For troubleshooting only; goes back to Off on restart.
- **Low memory mode**: processes one image or plate solve at a time. Turn it on for a
  Raspberry Pi or another computer with little memory, if astrolol gets killed while
  downloading images.

## Plugins

Lists every feature that can be turned on, grouped like the menu (Equipment, Astronomy,
Settings), with a description. Tick or untick, then click **Restart now**: changes take effect
after a restart (*Restart required to take effect*).

Some plugins bring others along: *Target* needs the object catalogue, the *Flat Wizard* needs
the *Sequencer*. Choose only one guider: *Built-in Guider*, *PHD2 Guiding* or
*Guide Simulator*.

## Server

- **Restart astrolol**: restarts the application. Connected devices are reconnected through the
  active profile.
- **Stop INDI server**: stops the INDI server and all INDI drivers. Use it if a driver is stuck;
  it is started again the next time an INDI device is connected.
