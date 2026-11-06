# Autofocus

*Plugin: Autofocus.* Moves the focuser through a series of positions, measures the stars at
each, and goes to the sharpest position. A camera and a focuser must be connected.

## Settings

Every change is saved as you make it, and the page opens on the camera you used last. The
[sequencer](../../sequencer/docs/en.md) runs its own autofocus with these same settings, so
you can adjust them while a sequence is running; they apply from the next autofocus.

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

**Doubtful results**: what to do when the curve looks unreliable. Each cause has its own choice:
**keep** (use the result and flag it), **retry** (measure again) or **stop** (the run fails and
the focuser goes back to where it started).

| Cause | Retry means |
|---|---|
| Minimum at the edge | Sweep again around the best position, up to two more times. |
| Flat curve | A new sweep with a longer exposure, centred on the best position. |
| Noisy curve | The same. |
| Too few stars | The same. A sky with no star at all is not measured again; the sequencer tries again later. |

**New sweeps allowed** limits the new sweeps for the last three causes. **Exposure of a new sweep**
is the multiple of the previous exposure, up to **Longest exposure**. Earlier sweeps stay on the
chart in grey. If a result cannot be fitted at all, the run fails whatever the choice.

## Running

Click **Start Autofocus**. During the run:

- the frame of the current step is shown (toggle **Auto-stretch** / **Linear**);
- the **V-Curve** chart fills in point by point (click a point to see its frame);
- **Progress** shows the step, position and number of stars;
- the status bar shows the run.

If the sharpest position is not inside the range you set (after changing filter, say, or as the
night cools), autofocus adds up to two more sweeps in that direction, so the number of steps
grows during the run. The result is then fitted on the positions around the best one. If it is
still not found, the run stops and says in which direction, and the focuser goes back to where
it started: start again from a position closer to focus.

**Abort** stops it and returns the focuser to where it started.

At the end, the fitted curve is drawn and the focuser moves to the **Optimal position**. The
**Result** shows it, with the best HFD/FWHM and how far it is from the starting position; the
ruler shows the start, the optimum and the current position.

The Result also says whether it can be trusted: **Reliable**, or **Doubtful** with the reason:

- the minimum is at the edge of what was measured (fewer than two good points on one side of it),
  so the position is an estimate;
- the sharpness hardly changes over the sweep (the stars are probably too faint for the blur to show);
- the measurements do not follow a clean V;
- several steps found too few stars (clouds, or a target near the horizon).

A doubtful result is still used; the sequencer journal records the verdict.

The [Sequencer](../../sequencer/docs/en.md) can run autofocus before a target, after each filter change,
after a meridian flip, every so many minutes or when the temperature changes.
