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
[Imaging](imaging.md) page) and by the [Sequencer](../../astrolol/plugins/sequencer/docs/en.md).

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

- **Server**: which server drives your INDI devices, and whether astrolol starts it. By default
  astrolol starts *indiserver* when the first device connects. It can instead use
  [INDIGO](https://www.indigo-astronomy.org) drivers, or a server you run yourself; this is set
  where astrolol is installed (environment variables, e.g. in its service file) and takes
  effect when it starts:
  - `ASTROLOL_INDI_SERVER_KIND=indigo`: INDIGO instead of indiserver (the Equipment page then
    lists INDIGO's drivers). `ASTROLOL_INDIGO_SERVER_PATH` if `indigo_server` is not found.
  - `ASTROLOL_INDI_MANAGE_SERVER=false`, with `ASTROLOL_INDI_HOST` and `ASTROLOL_INDI_PORT`
    (7624 by default): a server you start yourself, possibly on another computer.
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
- **Stop INDI server**: stops the INDI server (indiserver or INDIGO) and all its drivers. Use it
  if a driver is stuck; it is started again the next time an INDI device is connected.
