# Polar Align

*Plugin: Polar Alignment.* Two ways to aim the mount's polar axis at the celestial pole: a
polar scope reticle, and a plate-solving wizard that measures the error and guides you while
you turn the adjustment knobs. A mount and a camera must be connected, and the site set in the
active profile.

![Polar Align](polar_align.png)

## Polar scope reticle

For mounts with a polar scope. The dot shows where Polaris should sit on the reticle right now,
with its **Angle**.

1. Turn tracking off.
2. Rotate the RA axis by hand until the reticle in your polar scope is oriented like the
   drawing.
3. Use the altitude and azimuth knobs to put Polaris where the dot is.

**Assume a typical inverting scope** is on by default: most polar scopes show the sky rotated
by 180°. Turn it off only if yours shows the sky upright.

## Plate-Solve Wizard

More precise, and it works without seeing the pole (the southern hemisphere has no bright
pole star). It needs [Plate Solving](../../platesolve/docs/en.md) to be set up.

**Settings**

- **Camera**, **Exposure (s)**, **Binning**: for the solves. The main camera or the guide
  camera both work.
- **Dec (°)**: the declination of the three points. Leave it on *Auto* to let the wizard choose
  a good one.
- **Live-adjustment rechecks**: exposure and search radius used while you turn the knobs. A
  shorter exposure and a small radius make each reading quicker. Leave the exposure blank to
  reuse the one above.

**Running it**

1. Click **Start 3-Point Fit**. The mount slews to three points at the same declination, on the
   side of the meridian it currently points at, and solves at each one (*Point 1 / 3*…).
2. The **Initial fit** shows the error in arcminutes, with what to do: *too high — lower the
   altitude*, *west of true north — increase azimuth*, and so on, and a rating
   (*Excellent*, *Good*, *Fair*, *Needs work*).
3. Turn the altitude and azimuth knobs in the indicated direction. Then click **Recheck now**:
   the **Latest reading** shows the remaining error. No new slew is needed.
   With **Auto-refresh** on, a reading is taken every few seconds without clicking; it keeps
   going even if you close the page.
4. Repeat until the rating is good enough, then click **Done**.

**Cancel** stops the run; **Start New Fit** starts over (for example after moving the tripod).

Tips: lock the knobs gently between readings, and do not touch the RA or Dec clutches during
the run, as this would invalidate the fit.
