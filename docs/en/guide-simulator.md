# Guide Simulator

*Plugin: Guide Simulator.* A guider without hardware. It stands in for PHD2 or the built-in
guider, so you can try the [Sequencer](sequencer.md) or dithering at your desk, and rehearse a
cloudy night. Do not enable it together with another guider.

## Using it

**Connect**, then **Start guiding**. The **Status** box shows the state, how long it has been
guiding, the RMS over the last minute and the number of losses. **Dither** behaves like a real
dither: the guider settles before saying it is done.

## Faults

Buttons inject the problems a real night brings:

- **Lose star 10 s**, **Lose star 2 min**, **Lose star until cleared**: guiding keeps trying and
  recovers when the star is back, as after a cloud.
- **Guiding stops**: as when PHD2 gives up; guiding must be started again.
- **Fail next settle**, **Fail next 3 settles**: dithers that do not settle in time.
- **Clear faults**.

## Settings

**Guiding RMS**, **Guide exposure every**, **Extra settling time**, **Pixel scale**,
**Time scale** (multiplies every simulated duration: below 1 the night runs faster), **A slew while guiding loses the star**, and
**Connected at startup**. Click **Save settings**.
