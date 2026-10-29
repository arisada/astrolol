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

The folder must be one astrolol may use: by default your home folder and astrolol's data
folder. To save elsewhere, on a USB drive for instance, add that place to `storage_roots` in
the configuration file `/etc/astrolol/astrolol.toml`, then restart astrolol. Otherwise the
setting is refused with the list of allowed folders.

## INDI Server

- **Server**: which server drives your INDI devices: *INDI* (indiserver, the default) or
  [*INDIGO*](https://www.indigo-astronomy.org), whose drivers the Equipment page then lists.
  Changes take effect when astrolol restarts; a **Restart astrolol** button appears until then,
  and the server astrolol started before is stopped at the restart.
  - **Started by astrolol**: on, astrolol starts the server when the first device connects. Off,
    it uses a server you start yourself, at **Host** and **Port** (7624 by default), possibly on
    another computer.
  - **INDIGO server program**: the program astrolol starts, shown here. It is set in the
    configuration file (`indigo_server_path`), not on this page.
  - **In use**: the server astrolol is using now.

  These can also be set where astrolol is installed, in its configuration file
  `/etc/astrolol/astrolol.toml` (`indi_server_kind = "indigo"`, `indi_manage_server`,
  `indi_host`, `indi_port`, `indigo_server_path`) or as environment variables
  (`ASTROLOL_INDI_SERVER_KIND`, …). A setting given this way is greyed out here.
- **Local image transfer**: the driver writes images straight to disk instead of sending them
  over the network connection. Faster, especially with large sensors.
- **INDI protocol logging**: *Off*, *Tags only* or *Full XML*. Records the traffic with the
  drivers in the [log](logs.md). For troubleshooting only; goes back to Off on restart.
- **Low memory mode**: processes one image or plate solve at a time. Turn it on for a
  Raspberry Pi or another computer with little memory, if astrolol gets killed while
  downloading images. It switches itself on at start when the computer has less than 2 GiB
  of memory.

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
