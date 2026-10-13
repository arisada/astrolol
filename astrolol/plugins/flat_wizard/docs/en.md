# Flat Wizard

*Plugin: Flat Wizard (needs the [Sequencer](../../sequencer/docs/en.md)).* Finds the right exposure for
flat frames, for each camera and filter, then queues the flats on the sequencer.

Set up your flat source first (a flat panel, a T-shirt over the dew shield at dawn…) and point
the telescope at it.

## Settings

**Cameras & filters.** Every connected camera, with one line per filter of its filter wheel
(from the profile; *No filter wheel* otherwise). Set the number of **frames** for each
combination you want (0 = skip it) and the **Gain** (empty = driver default).

**Target**

- **Target full well (mean)**: how bright the flats should be, as a share of the sensor's full
  scale. Around half is the usual choice.
- **Tolerance**: how close to that is good enough.
- **Saturation guard**: a trial with more than this share of clipped pixels is treated as
  too bright.

**Trial exposures**: **Starting duration**, **Max duration** (safety cap), **Binning**,
**Max attempts**.

## Running

Click **Solve & Queue Flats**. For each camera and filter, the wizard takes short trial
exposures and adjusts the duration until the brightness is on target. **Live trials** shows
each attempt (duration, brightness, *saturated*); **Results** shows the duration found and how
many trials it took.

Each solved combination is added as a task to the sequencer queue (*Queued on the sequencer*),
with the frame count you chose. Start the [Sequencer](../../sequencer/docs/en.md) to take them.

**Abort** stops the trials.
