# Sequencer

*Plugin: Sequencer.* Plans and runs a night of imaging: a queue of tasks, each one a target
and the frames to take on it. For each task the sequencer can slew, centre, start guiding,
focus, then take the frames, dithering between them and flipping at the meridian when needed.
It can be paused, stopped and resumed at any point, and writes a journal of every run.

The page has three tabs: **queue**, **journal** and **settings**.

## The queue

The queue is the list of tasks, run from top to bottom. Each card shows the target, the plan
(*slew · center · guide · dither every 3 · on error: pause*…), the progress
(*12/40 frames · 1 h / 3 h 20*) and the status: *pending*, *running*, *interrupted*,
*completed*, *failed* or *skipped*.

- **Add task** opens the task editor.
- Drag cards to reorder them.
- **Clear done** removes the completed tasks.
- **Sequences…** saves and loads whole queues (see below).

The **⋯** menu of a card: **Edit**, **Duplicate**, **Download as a file**,
**Start from here** (earlier pending tasks are left for later), **Switch to this task** (after
the current frame; the current task keeps its progress), **Skip** / **Unskip**,
**Reset progress**, **Delete**. Deleting a task never deletes the frames already on disk.

## Adding a task

![Task editor](tasks.png)

**Target.** Four ways to choose it:

- **Search**: a catalogue object or a planet (planets are looked up again when the task starts,
  so the position is current).
- **Favorites**: from the [Target](../../target/docs/en.md) page.
- **Mount pointing**: no slew and no centring; the task images wherever the mount points when
  it starts. Use it for flats, darks, or a framing you set up by hand. The name is optional and
  only labels the frames.
- **Coordinates**: RA in hours (`5 35 17` or `5.588`), Dec in degrees (`-5 23 28` or
  `-5.39`), J2000.

**Task name** (optional): defaults to the target's name.

**Cameras.** Choose the camera, optionally **Set temperature** for it, then add one row per
group of frames:

| Column | |
|---|---|
| Filter | When the camera has a filter wheel in the profile. |
| Exposure (s) | |
| Count | Number of frames. |
| Gain, Bin, Type | Gain (empty = camera default), binning, frame type (light, dark, flat, bias). |
| Total | Exposure time of the row. |

**Add group** adds a row; the arrows reorder rows. **Order**: **Group by group** takes all the
frames of a row before the next one; **Round robin** cycles through the rows,
**Frames per turn** at a time, so you get some of every filter even if the night is cut short.
**Autofocus after each filter change** refocuses when the filter changes.

**Several cameras.** **Add a camera** to image with two or more cameras on the same mount (for
example a mono camera and a colour camera on two telescopes). The **Primary** camera leads: the
task dithers after its frames and does the meridian flip. The other cameras never move the
mount: they only start a frame that ends before the primary's next dither or flip, and
otherwise wait. Under each secondary camera, astrolol tells you which share of the time it will
actually expose; shorter exposures on the secondary waste less. **Make primary** changes which
camera leads.

**Before imaging**, each optional. Whenever one of the first three runs, tracking is switched on
first if the mount was not tracking:

- **Slew to the target**
- **Center with plate solving** (needs [Plate Solving](../../platesolve/docs/en.md))
- **Start guiding (wait for settle)** (needs a guider)
- **Autofocus** (needs [Autofocus](../../autofocus/docs/en.md))
- **Wait for cameras to reach temperature**
- **Flat panel: close the cover and light it, open it afterwards**: for flats. The cover of
  the flat panel under the camera's telescope in the profile is closed and the light switched
  on before the frames, and the light is switched off and the cover opened when the task ends,
  pauses or fails. A **Panel** column appears in the exposure table to set the brightness of
  each row (empty = leave the panel as it is), so each filter can have its own. Switching this on
  also switches off slewing, centering, guiding and dithering, which flats do not need.

**While imaging**: **Dither every** *n* primary frames, and an optional **Delay between frames**.

**If a step fails**:

| Choice | What happens |
|---|---|
| pause | The whole run pauses; **Resume** retries the failed step. |
| skip | This task is marked failed and the next one starts. |
| defer | This task is set aside (it can be resumed later) and the next one starts. |
| abort | The whole run stops. |

Click **Add to queue** (or **Save changes** when editing). When you edit a task that has
already started, frames already taken are kept for the rows whose filter, duration, gain,
binning and type are unchanged.

## Running

The bar above the queue:

- **Start** (or **Start / resume**) runs the queue from the first unfinished task. Problems that
  would stop the run (no camera, a filter that does not exist…) are listed first, on the tasks
  concerned.
- **Pause** pauses after the current frame. Its menu also offers *Pause after this task* and
  *Pause now* (aborts the exposure in progress; that frame is lost). **Resume** continues.
- **Stop**, with the same three choices.
- **Skip task** moves on to the next task.

While running, the bar shows the current task and activity (*Slewing*, *Centering*,
*Starting guiding*, *Focusing*, *Exposing*, *Dithering*, *Meridian flip*…), the exposure in
progress for each camera, the number of tasks done and the exposure time left.

Progress is saved as the run goes. If astrolol, the computer or the network goes down, start
again and the queue resumes where it was; a task interrupted for a long pause is re-centred
before it continues.

**When something goes wrong** the sequencer tries to save the night:

- **Guiding is down**: it waits for guiding to come back before the next frame, retries
  starting guiding regularly, re-centres once if guiding stays down, and can retake frames that
  were taken unguided.
- **Centering finds no stars** or **Autofocus is failing** (clouds): it retries
  automatically. During an autofocus stall imaging continues at the last good focus.
- The bar shows what is stalled, since when and when the next attempt is due. Switch to another
  task or stop if the sky will not clear. With **Give up on a stall after** set, the task is
  handled as a failed step after that time.

**Paused on an error**: the bar shows the error. **Resume (retry)** retries the failed step;
**Skip task** moves on.

## Sequences

**Sequences…** opens the library:

- **Save the queue as a sequence**: a name, an optional description, and whether to
  **Leave out completed tasks**. Only the definitions are saved (targets, cameras, exposures,
  options), not the progress.
- **Saved sequences**: **Load** adds fresh copies of the tasks to the queue; download or delete
  them.
- **Files**: **Download the queue** as a file, **Add a file to the queue**, or
  **Add a file to the saved sequences**. Use this to prepare a plan on another astrolol or to
  keep backups.

## Journal

![Journal](journal.png)

A journal is written for every run. The list shows when each run started, how long it lasted,
its outcome, its targets, the number of frames and the total integration. Click a run to see:

- **Integration**, **Frames saved** (and how many were not counted), **Interruptions / stalls**,
  **Failed steps**;
- **Where the time went**: a bar and a timeline of imaging, slewing / centring / flipping,
  guiding / dithering, focusing, pauses and waiting. Hover the timeline for details;
- **Captured**: frames and time per target, camera and filter;
- **Events**: centring results, guiding interruptions, autofocus runs, flips, pauses, failures;
- **Frames**: every frame with its time, target, camera, filter, exposure, guide RMS, unguided
  time, altitude, focus position and sensor temperature.

**Report (Markdown)** and **Frames (CSV)** download the run's report and frame list.

## Settings

Defaults for every run, grouped by topic. The most useful ones:

| Group | Settings |
|---|---|
| Mount | **Unpark when a run starts**, **Park when the queue is done**. |
| Meridian flip | **Flip at frame boundaries** at a given **hour angle** past the meridian, **Center after the flip**, **Refocus after a meridian flip**. |
| Guiding | **Settle threshold** (px), **Settle time**, **Settle timeout**. |
| Dither | **Amount** (px), **RA only**. |
| Centering | **Tolerance** (arcsec), **Max attempts**, **Exposure**, **Binning**. |
| Several cameras | Time allowed after a secondary frame, and a warning when a secondary exposes too little of the time. |
| Guiding loss and stalls | How long guiding must be steady before a frame, how often to retry guiding, centring and autofocus, when to re-centre, when to give up, and whether to retake frames unguided for too long. |
| Autofocus | **Refocus when the temperature moved** by some °C, **Refocus every** some minutes. |
| Session journal | **Journal folder** (default: `journal` next to the saved images). |
| Resume and timeouts | Re-centre after a long pause; timeouts for slews, flips, parking and exposures. |
| Camera cooling | Warm the cameras up when the queue is done, how close to the set point is close enough, how long to wait for it. |

Click **Save settings**.
