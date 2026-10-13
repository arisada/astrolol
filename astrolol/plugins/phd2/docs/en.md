# PHD2 Guiding

*Plugin: PHD2 Guiding.* Lets astrolol use [PHD2](https://openphdguiding.org/) as its guider:
shows its state and guide graph, starts and stops guiding, and dithers between frames. Do not
enable it together with the [Built-in Guider](../../guider/docs/en.md) or the
[Guide Simulator](../../guide_simulator/docs/en.md).

PHD2 runs as a separate program, on the telescope computer or another machine. In PHD2, turn on
**Tools → Enable Server**. PHD2 connects to the guide camera and the mount itself; with an
[EQMOD](../../eqmod/docs/en.md) mount, pick the *astrolol Mount Proxy* as PHD2's mount.

## Connecting

Open the settings (**Graph & debug settings**), set the **PHD2 host** (`localhost` if PHD2 runs
on the telescope computer) and **PHD2 port** (4400 by default), then click **Connect**.

## The page

- **State**: *Looping*, *Calibrating*, *Guiding*, *Settling*, *Star loss*, *Paused*,
  *Stopped*…
- **Guide error graph** in arcseconds, with **RMS RA**, **RMS Dec**, **RMS average**, the star's
  **SNR** and the **Pixel scale**.
- **Guide** starts guiding (PHD2 calibrates first if needed), **Pause** / **Resume**, **Stop**.
- **Dither once** moves the guide position a little and waits for PHD2 to settle.

Settings: **Graph vertical scale**, **Samples shown**, and **PHD2 debug logging** (records the
traffic with PHD2 for troubleshooting).

Automatic dithering between frames is set on the [Imaging](../../../../docs/en/imaging.md) page (while looping)
or in the [Sequencer](../../sequencer/docs/en.md).
