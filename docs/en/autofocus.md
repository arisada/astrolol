# Autofocus

*Plugin: Autofocus.* Moves the focuser through a series of positions, measures the stars at
each, and goes to the sharpest position. A camera and a focuser must be connected.

## Settings

**Camera** and **Focuser**: which ones to use. Choose a focuser that sits in front of the
camera in the profile.

**V-Curve**

| Setting | |
|---|---|
| Sharpness metric | **HFD** (half-flux diameter) or **FWHM**. HFD copes better with very defocused stars. |
| Fit algorithm | **parabola** or **hyperbola**. Hyperbola follows the real shape of a V-curve better when the sweep is wide. |
| Step size | Focuser steps between two positions. |
| Steps each side | Positions on each side of the start; the total is shown. |
| Start position | Centre of the sweep. Empty = the current position; **Use current position** fills it in. |
| Track the same stars | Measure the stars found on the first frame at every step, instead of a fresh set each time. Steadier results in a field with few stars. |

A good sweep goes from clearly out of focus on one side to clearly out of focus on the other.
If the curve looks flat, increase the step size; if the stars disappear at the ends, reduce it.

**Exposure**: **Duration**, **Binning**, **Gain** (empty = driver default), and **Filter**
(**Keep current** or a slot). Use a few seconds; enough to see a dozen stars.

## Running

Click **Start Autofocus**. During the run:

- the frame of the current step is shown (toggle **Auto-stretch** / **Linear**);
- the **V-Curve** chart fills in point by point (click a point to see its frame);
- **Progress** shows the step, position and number of stars;
- the status bar shows the run.

**Abort** stops it and returns the focuser to where it started.

At the end, the fitted curve is drawn and the focuser moves to the **Optimal position**. The
**Result** shows it, with the best HFD/FWHM and how far it is from the starting position; the
ruler shows the start, the optimum and the current position.

The [Sequencer](sequencer.md) can run autofocus before a target, after each filter change,
after a meridian flip, every so many minutes or when the temperature changes.
