# The dock

The dock is a side panel on the right that keeps a few read-outs in view whatever page you are on:
where the mount points, how well the guider is doing, and so on. It never changes the page you are
working on.

## Opening it

Click the small tab on the right edge of the screen (at the bottom of the screen on a phone held upright, where the dock opens as a sheet over the bottom of the page). On a wide screen the page makes room for the
dock; on a narrower one the dock slides over the page (press **Esc** or the close button to put it
away). Whether it is open is remembered by each browser.

## Choosing what it shows

1. Click **Edit the dock** (the pencil) at the top of the dock.
2. Pick widgets from the **Add a widget** list. A widget that shows one device, such as a focuser or a
   filter wheel, is listed once per connected device, so two focusers can both be pinned.
3. Use the arrows to reorder widgets and **×** to remove one. Click **Done editing** when finished.

Click a widget's title to go to the page it comes from, or the chevron to fold it.

The layout is saved with your other settings, so it follows you to your phone or another computer.
Viewers who are not allowed to change settings can arrange the dock, but it resets when the page is
reloaded.

## Available widgets

| Widget | From | Shows |
|---|---|---|
| Position | [Mount](mount.md) | Coordinates and the mount on the sky |
| Horizon | [Mount](mount.md) | The mount over the local horizon |
| Mount state | [Mount](mount.md) | Parked, slewing or tracking, pier side, time to the meridian |
| Focuser | [Imaging](imaging.md) | Focuser position on a ruler |
| Filter wheel | [Imaging](imaging.md) | The filter in the beam |
| Warnings | [Logs](logs.md) | Warnings and errors from every component |
| Sequence | [Sequencer](../../astrolol/plugins/sequencer/docs/en.md) | Current task, frames done, time left |
| Focus curve | [Autofocus](../../astrolol/plugins/autofocus/docs/en.md) | The V-curve and the best position found |
| Guiding | [Guider](../../astrolol/plugins/guider/docs/en.md) | Guiding or lost, star signal, last correction |
| Target visibility | [Target](../../astrolol/plugins/target/docs/en.md) | When the current target is up tonight |
| Last solve | [Plate Solving](../../astrolol/plugins/platesolve/docs/en.md) | Last solved position and its offset from the mount |
| System health | [System](../../astrolol/plugins/system/docs/en.md) | Processor, memory, disk, temperature, power |

Widgets of a feature you have switched off are not offered.
