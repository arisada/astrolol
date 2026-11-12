# Stacked camera

*Plugin: Stacked camera.* Guide and take long exposures with the same camera. The guider gets a
short frame every few seconds, and a long exposure is built from those same frames, so one camera
does both jobs and no second camera or guide scope is needed.

## Using it

1. Connect your camera in [Equipment](../../../../docs/en/equipment.md).
2. Open **Stacked camera** and click **Use for guiding and imaging** next to the camera. Two
   cameras appear in the equipment list: the one marked *imaging* takes the exposures, the one
   marked *guiding* gives the guider its frames.
3. Choose the second one as the guide camera in the [Guider](../../guider/docs/en.md) and the
   first one in [Imaging](../../../../docs/en/imaging.md) or the
   [Sequencer](../../sequencer/docs/en.md).

**Stop using** disconnects both; the real camera stays connected.

## Keeping it after a restart

**Use for guiding and imaging** connects the two cameras for this session only. To have them
connected with the rest of your equipment, add them to your [profile](../../../../docs/en/profiles.md):

1. In [Equipment](../../../../docs/en/equipment.md), add a camera, choose **Other adapter**, and
   enter the adapter `stacked_camera_long` (for imaging) or `stacked_camera_fast` (for guiding).
2. As **Connect params** give the device ID of your real camera, as shown in Equipment:
   `{"source_id": "your_camera_id"}`.
3. Put both new cameras in the profile's equipment tree, after the real camera, so that camera
   is connected first.

## Short frames

**Short frame length** is how long each frame lasts. The guider corrects once per frame, so
shorter frames guide faster. A long exposure is a whole number of short frames: 300 s with 2 s
frames is 150 frames, and an exposure that is not a multiple is rounded up (the saved file says
how much light it really holds). A longer frame adds less noise to a long exposure, so pick the
longest one your guiding allows. The change applies the next time the camera starts streaming.

Set the guider's own exposure to the same value, so its dark frames match.

## While it runs

The **Camera stream** box shows whether the camera is streaming, how many frames it has
produced, how many were lost along the way, and the share of time the sensor was exposing (below
100 % means the camera needs time between frames, and that time is not collected as light). A
long exposure shows in the status bar as *Stack* with the seconds collected so far.

An exposure that cannot finish (the camera stops sending frames, or is unplugged) ends with an
error; the next one starts again.

## Calibration

The saved image is the plain sum of the short frames, in 32-bit integers, with nothing removed.
Take dark frames the same way, with the lens cap on and the same exposure and short frame length,
and calibrate as usual.
