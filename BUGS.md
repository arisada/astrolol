# Bugs

Here's a list of bugs observed and to be fixed

## Imaging panel

We should have one panel per connected camera. Right now, only the first camera can be used to take pictures.

## Reshape the "equipment" page

The "equipment" page does not match the way indi works and it causes problems, because we expect to know the exact model of the device to be plugged before the driver is loaded. It causes problems when drivers bring more than one device.
Suggestion: The current "add a device" panel stays and propose to load all kind of drivers (add more than mounts/cams/AF), but eventualy only selects an indi driver to load. It's useless to load a single driver more than once. Devices detected by Indi would be **registered** automatically. A registered device is a device that is recongized by indi and always shows up in the "connected" device list (rename this to "registered"). Don't automatically connect the devices (connect = send an indi CONNECT command).

The user profile can work mostly the same - it contains the drivers and id/name of devices that are to be recognized.

### Todo
User profile should contain optical paths, that link a telescope with one or two imagers and one or two filterwheels, focusers etc.

## Indi debugging

Add a checkbox in "Indi Server" advanced options to allow debugging. All commands sent (and received codes) would show up in logs for further debugging.

## Lost frames and platesolve hanging

After a failed or aborted exposure, the platesolve module stops working or takes a very long time to restart. The astap process just doesn't start until the whole procedure times out completely. (Note: the `CCD_ABORT_EXPOSURE` type error visible in related logs has been fixed, but the root platesolve hang may be a separate issue.)

## stack traces should go in astrolol.log

Missed stack traces are not written to the log file.

## Missing filterwheel support

This issue is related to the indi driver model above. Adding a fake focuser with indi_asi_wheel driver (set manually) allowed me to register the filter wheel because it got recognized by the auto probing. This would have been easier though by selecting the efw from a list.

## Manual focuser move

The position of the focuser should move in realtime if possible. The arrows should be blocked until moving is possible again so we don't raise an error.

### Todo

Add a focusing page, that gives more tools for focus. Autofocus (when available) but also fhwm per frame in a rolling graph to help with manual focus.

## Imager

### Todo
- Resizable image window, with controls (maximize picture, 1-by-1 pixel, move/zoom through image)
- Histogram graph
- Improve auto-stretching that's currently too extreme.
- Show FWHM.

## Incomplete logging

Some events don't seem to make it into the log page. The log filters buttons are incomplete and keep getting incomplete when new event types are implemented. The filters buttons should be added dynamically based on the log entries already received.

## UI uniformization

The pages seem a bit "off". Some of the UI elements are present in all pages but not at the same place or with the same look&feel. The project could lose some weight on the UI side by refactoring the UI and deciding once for all how to show a configuration tab, which icon to use for which kind of device, etc.

### Todo
- Some elements from pages would be nice to have as widgets, that can be opened or even moved in other pages like in Home Assistant. For instance having the mount's direction cross would be useful when attempting to center an object.

## Mount's 'nudge' rates inconsistent

The proposed rates do not follow the standard of x times tracking speed, with the fastest being 800x, as seen in TELESCOPE_SLEW_RATE.
