# The interface

## Menu

The menu on the left is split into three groups that can be folded:

- **Equipment**: Equipment, Profiles, and equipment-related plugins (EQMOD, Bluetooth Serial,
  Stellarium, LX200…).
- **Astronomy**: Target, Mount, one entry **per connected camera** (named after the camera),
  and observing plugins (Plate Solving, Autofocus, Guider, Sequencer, Viewer…).
- **Settings**: Security, System, mDNS, Logs, Options.

An entry carries a mark when something is going on there: a faint pulsing ring means *active*
(an exposure, a sequence running, guiding); a red dot means *needs attention* (star lost, a run
stalled). A folded group shows the most serious mark of its entries.

The arrows at the bottom of the menu collapse it to icons.

## Status bar

The bar at the top is a live readout of everything that is connected, for example:

```
MOUNT Tracking │ CCD SIMULATOR Idle │ CCD SIMULATOR Cooling -14°C │ GUIDER guiding     ADMIN ⇥  LIVE
```

- One chip per device: mount (*Slewing*, *Tracking*, *Not tracking*, *Parked*), camera
  (*Idle*, *Loop*, *Downloading…*, *Cooling*), focuser (*Moving*), rotator.
- Plugins add their own chip while they are busy: sequencer, guider, autofocus, plate solving,
  polar alignment, flats, power warnings…
- On the right: who is signed in (with a sign-out button) and the connection state. **live**
  means updates are arriving; **reconnecting…** means the browser lost the server and is trying
  again. Nothing is lost on the server side: astrolol keeps working while no browser is open.

States are always written in words; the colour is only a second cue, so the bar stays readable
in the red night palettes.

## Pop-up messages

Errors and confirmations appear briefly at the corner of the screen. Click **Dismiss** to close
one; it stays closed after a page reload.

## Device properties

On the Imaging and Mount pages, the small gear next to a device name opens
**Device properties**: every setting the INDI driver exposes, grouped as the driver groups them,
plus the **messages** the driver sent. Use it for anything astrolol does not show on its own
pages (USB bandwidth, read-out mode, driver-specific options). Change a value and click **Set**.

## Palettes and languages

Options → **Palette** changes the colours. *Night red* and *Night crimson* keep your eyes
dark-adapted at the telescope. Options → **Language** switches between English and French.
Both are remembered by the server, so every browser gets the same choice.

## Phones and tablets

astrolol is usable on a phone. On a narrow screen the side panels fold away (use the arrow at
the top of a panel to open or close it) and the menu becomes a row of tabs.

## Several people at once

Every browser sees the same state live. If [Security](security.md) is on, each person signs in
with their own level: read-only viewers can watch, operators can drive the telescope, admins can
also change settings, plugins and equipment.
