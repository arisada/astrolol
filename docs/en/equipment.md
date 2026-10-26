# Equipment

> **Setting up astrolol for the first time?** Start with [Getting started](getting-started.md):
> it takes you from connecting your first device to a profile you can connect in one click.

The Equipment page has two tabs:

- **connections**: the devices connected right now, and the wizard to connect new ones.
- **inventory**: everything you own, connected or not. Profiles are built from it.

**Refresh** re-reads the list of devices from the server.

## Connections

### Connecting a device

Click **Load driver** and follow the wizard.

1. **What do you want to connect?** Camera, Mount, Focuser, Filter Wheel, Flat Panel or Rotator.
2. **How is it connected?**
   - **Browse INDI drivers**: almost all commercial hardware. astrolol starts and stops the INDI
     server by itself (this can be changed in [Options](options.md#indi-server)). When astrolol
     uses INDIGO, this reads **Browse INDIGO drivers** and lists INDIGO's drivers instead; a
     camera's filter wheel or focuser that INDIGO shows as a device of its own connects with
     the camera.
   - **Other adapter**: drivers provided by astrolol plugins, for example `eqmod` (the native
     Sky-Watcher driver from the [EQMOD](../../astrolol/plugins/eqmod/docs/en.md) plugin) or its mount simulator,
     and the `alpaca_…` adapters of the [ASCOM Alpaca](../../astrolol/plugins/alpaca/docs/en.md) plugin.
     If none is offered for the chosen kind, the wizard says so.
3. For INDI: **Select manufacturer**, then **Select model**. **Enter manually…** lets you type a
   driver name (`indi_asi_ccd`) and, optionally, the name the driver announces the device
   under (useful when one driver serves several identical devices).
4. **Configure & connect**: the driver is loaded and the settings it accepts before connecting
   are listed: serial port, baud rate, and so on. Leave them as they are unless you know you
   need to change them. If the driver serves several devices, choose the **INDI device name**.
   With INDIGO, the settings that belong to the INDIGO server (its profiles, additional
   instances, a password) are shown greyed out: they are not changed when connecting.
5. **Device ID** (optional): a short name used everywhere in astrolol (menu entries, file
   names). Letters, digits, `-` and `_`. Leave it empty and one is made from the device name.
6. **Connect**.

For an **Other adapter**, the wizard asks for the adapter, an optional device ID and its
**Connect params** as JSON (each adapter documents its own, e.g. `{"port": "/dev/ttyUSB0"}`).

### Connected devices

Each connected device shows its kind, its ID, its driver and its state (*connected*,
*connecting*, *busy*, *error*…). Devices that came along with another one (a filter wheel built
into a camera, for instance) are marked *auto-discovered*.

The buttons on each row:

| Button | Effect |
|---|---|
| Import to inventory | Adds the device, with its driver, to the inventory. Greyed out when it is already there. |
| Reconnect | Disconnects and connects again. Try this first when a device stops answering. |
| Disconnect (keep registered) | Disconnects but keeps the device in the list, ready to reconnect. |
| Remove device | Disconnects and removes it from the list. |

A device that is not part of the [active profile](profiles.md) is marked **not in profile**.
Such a device may not work properly with the rest of astrolol, which relies on the profile to know
how it is mounted (which telescope, filters and site go with it). Hover the mark for what to do:
import the device to the inventory if needed, then add it to the profile's equipment tree on the
Profiles page. Nothing is marked while no profile is active.

Right after a device connects, astrolol offers to add it to the inventory if it is not there
yet.

## Inventory

The inventory is your equipment list. Each item has a type:

| Type | What to fill in |
|---|---|
| Observation Site | Latitude, longitude, altitude (m), time zone |
| Mount | Driver (see below) |
| Telescope / OTA | Focal length (mm), aperture (mm) |
| Camera | Driver, pixel size (µm), default gain |
| Filter Wheel | Driver, filter names (comma-separated, in slot order) |
| Focuser | Driver |
| Rotator | Driver |
| Flat Panel | Driver (a light panel, a motorised dust cover, or both) |
| GPS | Driver |

**Add equipment** opens the form; each item has **Edit** and **Delete** buttons.

An item whose device is registered on the Connections tab (see [Connected devices](#connected-devices)) shows its state
(*connected*, *busy*, *error*, *disconnected*…) next to its name. An item with no state is not
connected. Sites, telescopes and GPS never show one.

For devices, the **INDI driver** (e.g. `indi_eqmod_telescope`) and the **INDI device name** (as
the driver announces it, e.g. `EQ6 Mount`) tell astrolol how to connect it. For a non-INDI
adapter, fill in the **Adapter key** (e.g. `eqmod`) and its **Connect params** instead. The
easiest way to get these right is to connect the device once through the wizard and use
**Import to inventory**.

Things worth filling in:

- **Site**: the mount needs it to compute where things are, and the [Target](../../astrolol/plugins/target/docs/en.md) page
  needs it for rise and set times. When the inventory has no site, a reminder offers
  **Add observation site**.
- **Telescope focal length** and **camera pixel size**: they give the image scale used by
  [plate solving](../../astrolol/plugins/platesolve/docs/en.md) and the [guider](../../astrolol/plugins/guider/docs/en.md), and are written into the FITS
  headers.
- **Default gain**: the gain the camera starts with. Leaving it to the driver is risky, as some
  drivers start at a gain you would never use.
- **Filter names**: shown wherever you choose a filter, and used in file names.

Next: put the items in a [profile](profiles.md).
