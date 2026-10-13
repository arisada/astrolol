# Imaging

There is one Imaging page per connected camera; each appears in the menu under the camera's
name. With no camera connected, the page says *No camera connected*.

![Imaging on a phone](../images/mobile.jpeg)

The page has the latest image in the middle, a log of camera, INDI and guiding messages below
it, and the controls on the right: the camera, then the focuser and filter wheel that sit in
front of this camera in the active [profile](profiles.md#the-equipment-tree).

## The image

The latest frame is shown with the stars' **FWHM** (in pixels) and the number of stars found,
handy for a quick focus check.

- Scroll or pinch to zoom, drag to pan. Double-click (or **reset**) to go back to the full view.
- The histogram in the corner shows the stretch curve and three numbers: **Bg** (sky
  background, median ADU; per channel on a colour camera), **σ** (background noise) and
  **Sat** (share of pixels at full scale). Keep *Sat* low on light frames and watch *Bg* on
  flats.

## Camera

**Cooling.** On a cooled camera, the gauge shows the sensor temperature, the set point and the
cooler power. Turn the cooler on with **Cooler ON / OFF**, choose the **Target °C** and click
**Set**.

**Exposure settings**

| Setting | |
|---|---|
| Frame type | Light, Dark, Flat or Bias. Written in the FITS header and file name. |
| Duration | Use − / + or click the value to type any duration. |
| Gain | The camera's gain; its valid range is shown next to the label. |
| Binning | 1×1 to 4×4. |
| Save subs | When ON, every frame is saved as FITS (see [Options → Image Saving](options.md#image-saving)). When OFF, frames are only shown. |
| Auto stretch | When ON, each preview is stretched to show faint detail. When OFF, you see the linear data. |

These settings are remembered per camera.

**Preview settings** (fold-out) change only how the image is displayed, never the saved file:

- **Fit** the image to the window, or **1x** (one image pixel per screen pixel).
- **JPEG quality**: lower it on a slow Wi-Fi link.
- **Stretch**: *soft*, *normal* or *hard*; **Advanced** adjusts the background level and the
  shadows clip.
- On a colour camera: show in **RGB** or **Mono**, with the channels **linked** or
  **unlinked** (unlinked balances each colour on its own, which removes a colour cast from
  light pollution).

**Guiding / Dither.** When a guider is running ([Guider](guider.md), [PHD2](phd2.md) or the
[Guide Simulator](guide-simulator.md)), astrolol can dither between frames while looping:
**Every N frames** or **Every N minutes** (0 = off; setting one clears the other).

**Buttons**

- **Expose** takes one frame.
- **Loop** takes frames one after the other until you click it again (**Stop**). The status bar
  shows *Loop* with the elapsed time.
- **Halt** aborts the exposure in progress and cancels the loop immediately.

For a planned night with several targets and filters, use the [Sequencer](sequencer.md).

## Focuser

Shown when the profile puts a focuser in front of this camera.

- The ruler shows the current position.
- **Move in** / **Move out** by the **Step size**.
- **Absolute position**, then **Go**, to move to a given position.
- **Halt** stops a move.

For automatic focusing, see [Autofocus](autofocus.md).

## Filter Wheel

Shown when the profile puts a filter wheel in front of this camera. Click a filter to move to
it; the names come from the [inventory](equipment.md#inventory) (*Filter 3* when unnamed).

## Device properties

The gear next to the camera, focuser or filter wheel title opens the driver's full list of
settings (*INDI properties*). See [Device properties](interface.md#device-properties).
