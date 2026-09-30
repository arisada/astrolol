# Viewer plugin — specification (v0.3)

## Goal

A plugin that lets the user browse every FITS frame astrolol has captured, inspect its
metadata, and preview it with the same stretch/histogram machinery as the live Imaging
page — independent of which camera captured it or whether that camera is even connected
right now.

## Non-goals (v1)

- No editing, calibration (dark/flat) application, or stacking.
- No filesystem watcher / continuous polling — indexing is a manual "rescan" plus live
  incremental indexing driven by `ExposureCompleted` (see below).
- No non-FITS formats, no cloud/export targets.
- No multi-mount rig support beyond a plain picker (see *Set as target*).

**In scope for v1** (both were "ideas" in the v0.2 review; both are now committed):

- Destructive removal, via a reversible **reject** action rather than a hard delete.
- Lightweight per-frame **quality metrics** (background level, star count, HFR) for light
  frames, used to sort/hunt for outliers in the frame table.

Indexing covers **any valid FITS file** found under the configured directory — not only
frames astrolol itself saved (e.g. a pre-existing capture library dropped into that
folder shows up too).

## Where the images live

A single configurable directory, `library_dir`, persisted like any other plugin setting
(`GET/PUT /plugins/viewer/settings`). Default is computed once, at first use, as the
static (non-templated) prefix of `UserSettings.save_dir_template` — everything before the
first `%` token (`~/astrolol_pictures/%D` → `~/astrolol_pictures`). If that prefix is
empty (e.g. a template starting `%D/...`), the default falls back to
`~/astrolol_pictures` rather than scanning the working directory or `/` — a bad template
must never turn into an accidental full-filesystem walk. The whole tree under
`library_dir` is scanned recursively, following `.fits`/`.fit`/`.fts`/`.fz`, **not**
following symlinks (avoids scan loops), and excluding the plugin's own cache directories.

**If `save_dir_template`'s root drifts away from `library_dir`** after the default was
computed (the user edits capture settings later without touching the viewer), newly
captured frames silently stop being indexed. The plugin checks this on `ExposureCompleted`
for every saved frame outside `library_dir` and shows a UI banner ("N recent captures are
outside the library at `<path>`") rather than failing silently.

**Changing `library_dir`** triggers a full rescan that (a) purges index rows whose `path`
no longer starts with the new root, and (b) garbage-collects cached thumbnails for any id
no longer present in the index.

## Architecture

```
plugins/viewer/
├── plugin.py          # ViewerPlugin — setup/startup (opens index db, subscribes to
│                       # EventBus), shutdown (closes db, cancels any in-flight rescan)
├── api.py             # FastAPI router — everything lives under /plugins/viewer/...
├── index.py           # ViewerIndex — sqlite3 catalogue: scan, incremental update, query
├── grouping.py         # per-frame-type group-key rules (see Grouping below)
├── coords.py           # header → ICRS conversion (WCS / OBJCTRA-DEC / RA-DEC), coord_source
├── quality.py           # lightweight background/star-count/HFR pass (light frames only)
├── models.py           # ImageRecord, GroupSummary, ViewerSettings, query param models
├── thumbnails.py        # thumbnail generation (from preview JPEG or from FITS) + cache GC
├── settings.py          # persisted settings (library_dir), defaults
├── ui/
│   ├── index.ts
│   ├── api.ts
│   ├── ViewerPage.tsx
│   ├── GroupList.tsx        # default view: aggregated session rows
│   ├── FrameTable.tsx       # frame list — used both for an expanded group and the
│   │                        # "flat" ungrouped view; differs only in which filters
│   │                        # it's given, not in behaviour (see API section)
│   ├── FilterSidebar.tsx
│   ├── RollupPanel.tsx      # per-object integration-time summary + disk usage
│   ├── ImageDetail.tsx      # single-frame view; shared ZoomableImage/HistogramOverlay/
│   │                        # LabeledSlider; next/prev keyboard nav
│   └── SettingsPanel.tsx    # library_dir field, rescan button/progress, rejected-bin controls
└── tests/
```

State lives on `app.state.viewer_index` (a `ViewerIndex` instance) — never a module
global, so each test's fresh `TestClient`/`FastAPI()` gets a clean index and cache dir.

## Data store: an embedded SQLite index

A single `viewer_index.sqlite3` (stdlib `sqlite3`, no new dependency) living next to
`profiles.json`. **One writer**: all mutating access goes through a single dedicated
worker (either a one-thread `ThreadPoolExecutor` or an `asyncio.Lock` guarding one
WAL-mode connection) — `sqlite3` connections are not safe to hand between arbitrary
`asyncio.to_thread` pool threads, and the rescan/live-indexer race below depends on
having one serialised writer. Reads may use their own short-lived connections.

Schema, one row per file:

| column | notes |
|---|---|
| `id` | hash of the absolute path |
| `path` | absolute path, unique index |
| `size_bytes`, `mtime` | for change detection |
| `captured_at` | from `DATE-OBS`, else file `mtime` |
| `captured_at_estimated` | `true` when `mtime` was used as a fallback (breaks after `cp`/`rsync` — flagged rather than trusted silently) |
| `frame_type` | light / dark / flat / bias / unknown |
| `object_name` | `''` when absent — **never `NULL`**, so "unnamed" filters/groups the same way everywhere |
| `exposure_s` | rounded to the millisecond at index time |
| `gain` | rounded to an integer at index time |
| `binning` | |
| `filter_name` | case/whitespace-normalised, `''` when absent |
| `camera_name` | from `INSTRUME` |
| `telescope_name` | |
| `ra_deg`, `dec_deg` | ICRS degrees, converted per `coord_source` (see *Coordinates*) — `NULL` when no coordinate could be determined |
| `coord_source` | `wcs` \| `header_icrs` \| `header_jnow` \| `null` |
| `ccd_temp`, `width`, `height` | |
| `night` | precomputed bucket string (see *Night bucketing*) |
| `sky_cell_ra`, `sky_cell_dec` | coarse rounded-coordinate cell, only populated when `object_name == ''` (see *Grouping*) |
| `bg_median`, `star_count`, `hfr` | nullable; light frames only (see *Quality metrics*) |
| `scan_generation` | see *Concurrency* |
| `indexed_at` | |

Indexes: `UNIQUE(path)`, `(night, object_name)`, `(captured_at)`, `(dec_deg, ra_deg)`,
`(frame_type)`. Group listing and date-range queries hit `(night, object_name)` /
`(captured_at)`; coordinate search hits `(dec_deg, ra_deg)`. Pagination uses **keyset**
pagination (`WHERE captured_at < :cursor ORDER BY captured_at DESC LIMIT :n`), not
`OFFSET`, so a page N query stays cheap regardless of library size. At the scale this
plugin needs to handle (tens of thousands of rows over years of use on a Pi), SQLite with
these indexes is not the bottleneck — SD-card I/O during the *first* scan of an imported
library is (see *Thumbnail cost*).

### Night bucketing

`night` is a stored column precisely because changing the rule later means reindexing —
so the rule is fixed here: bucket by **local solar time**, using `SITELONG` when the
frame's header has it to estimate a longitude-based offset from UTC, else the server's
configured system timezone, with the boundary at local noon (a session starting before
midnight and continuing after groups together). `DATE-OBS` is always UTC; this conversion
happens once, at index time.

### Coordinates (`coords.py`)

Indexing "any FITS file" means headers won't all look like astrolol's own. At index time,
try in priority order and record which one succeeded as `coord_source`:

1. **WCS** (`CRVAL1`/`CRVAL2` + the rest of the WCS keywords) — preferred when present,
   since it reflects a plate-solved position rather than where the mount *reported* it
   was pointing.
2. **`RA`/`DEC`** in ICRS degrees (astrolol's own header patch).
3. **`OBJCTRA`/`OBJCTDEC`** sexagesimal strings with `EQUINOX`, common in other capture
   tools — parsed and precessed to ICRS.

When none resolve, `ra_deg`/`dec_deg`/`coord_source` stay `NULL`, and "set as target" is
disabled for that frame. The `ImageDetail` tooltip on the coordinates says explicitly that
a `header_icrs`/`header_jnow` source is the mount's *reported* pointing, not a solved
position — only `coord_source == "wcs"` represents an actual measurement.

### Concurrency: rescan vs. the live indexer

The live indexer (subscribed to `ExposureCompleted`) and a manual rescan can run at the
same time. Two rules avoid the previous design's data-loss bug (a rescan deleting a row
the live indexer just inserted mid-walk):

- Every row write is stamped with the current `scan_generation` (an integer bumped at the
  start of each rescan). A rescan's "remove rows for files no longer on disk" step only
  deletes rows where `generation < this_scan's_generation AND indexed_at < scan_start_time`
  — a row written *during* the walk by the live indexer is never eligible for deletion by
  that same walk.
- Rescan is **single-flight**: `POST /plugins/viewer/rescan` returns `409` if one is
  already running, and the running scan is cancellable (`DELETE` on the same endpoint, or
  a `cancel: true` body) and cleans up on `asyncio.CancelledError` like any other
  long-running task in this codebase.

`ExposureCompleted` events with no `fits_path` (unsaved preview-only exposures, e.g.
plate-solve loops) are a no-op for the indexer.

### Thumbnail cost

Reading headers only is cheap (`astropy.io.fits.getheader()`, no pixel data touched).
Generating a thumbnail is not — it means decoding the full pixel array, roughly 1–2s per
50MB frame on a Pi, which would mean hours for a freshly-imported 20k-frame library.

- **Live captures**: don't re-read the FITS at all. Downscale the JPEG the core imager
  already generated (`preview_path` on `ExposureCompleted`) with a cheap Pillow resize —
  this doesn't compete with an active imaging session for CPU.
- **Rescanned/imported frames**: thumbnails are generated **lazily**, on first request
  from the UI, not eagerly during the scan. A rescan only ever touches headers.
- Thumbnail filenames include `(size, mtime)`, so a file replaced at the same path
  invalidates its cached thumbnail automatically.

This needs one small, additive change to core `astrolol/imaging/preview.py`: let
`_resize_for_preview`'s target size be overridable, and add
`fits_to_thumbnail(fits_path, out_path, max_dim=256, quality=70)` for the
lazily-generated (imported-library) case, using the same default 50th/99th stretch. This
is a core change, not plugin code, and gets its own unit test in `tests/unit/`.

## Grouping

Astrophotography sessions are repetitive by design — the same target/filter/settings shot
dozens to hundreds of times a night. A flat thumbnail grid of near-identical frames
doesn't help anyone eyeball anything, so the **default view groups frames**, rendering one
row per group: one representative thumbnail, frame count, total integration time, date,
filter, exposure, and representative coordinates.

```
[thumb]  M42 · Ha · 300s · bin1 · gain100 — 2026-09-29 — 42 frames · 3h30m
[thumb]  (unnamed) · L · 60s · bin2 · gain50  — 2026-09-14 — 180 frames · 3h00m
```

The representative frame is picked **at query time** as `MIN(captured_at)` within the
group — not a stored row reference — so deleting/rejecting that frame just shifts the
representative to the next one; a group has no separate identity to go stale.

**The group key is per `frame_type`**, because "same session" means different things for
different frame types:

| frame_type | key |
|---|---|
| light | `object_name` (or `sky_cell` — see below), `filter_name`, `camera_name`, `exposure_s`, `binning`, `gain`, `night` |
| flat | `filter_name`, `camera_name`, `binning`, `gain`, `night` — **drops `exposure_s`**, since auto-exposure sky flats vary it frame to frame; grouping on it would give one group per frame |
| bias | `camera_name`, `binning`, `gain`, `night` — drops `exposure_s` only. **Gain is kept**: bias frames at different gains aren't the same calibration set and must not collapse together |
| dark | `camera_name`, `exposure_s`, `binning`, `gain` — **drops `night`**, since dark libraries are captured once and reused across months; forcing them into nightly groups would fragment a single dark library into dozens of one-off groups |

`exposure_s`/`gain` in the key use the rounded values already stored, so float drift
between frames of "the same" session doesn't split the group.

**Blank `object_name` on lights**: two different untracked targets shot the same night at
the same settings would otherwise collapse into a single group — exactly the case "set as
target" exists to solve, so this is the one grouping bug that directly undermines the
plugin's own headline feature. Fix: when `object_name == ''`, append a coarse sky cell to
the key instead — `round(dec_deg)` and `round(ra_deg * cos(dec_deg))`, stored as
`sky_cell_ra`/`sky_cell_dec` at index time — so distinct blank-name pointings only merge
if they're genuinely within about a degree of each other.

**Expanding a group is not a separate endpoint.** There is no `group_key` encoding: a
group is fully described by the field values above, so expanding one is just
`GET /plugins/viewer/images` called with those same values as ordinary filters (e.g.
`?frame_type=light&object=M42&filter=Ha&exposure_s=300&binning=1&gain=100&night=2026-09-29`).
`GroupList.tsx` and `FrameTable.tsx` are the only two views; the latter is also what
backs the "flat/ungrouped" toggle — same component, just given a different filter set (no
grouping fields, or the full unfiltered range). This also directly answers whether there's
a separate "core" fetch API vs. a management API: there isn't — everything, browsing and
mutation alike, is one plugin router under `/plugins/viewer/...`.

## Quality metrics (light frames only)

`bg_median` comes for free — it's already returned by `fits_to_jpeg`'s stats dict, and
gets recorded whenever a thumbnail/preview is generated for a frame.

`star_count`/`hfr` need real pixel analysis, which is too expensive to run inline during
indexing (same cost problem as thumbnails, worse — it needs full-resolution or
near-full-resolution data, not a 256px thumbnail, to be meaningful). They're computed by a
**self-contained, low-priority background task queue** (`quality.py`), decoupled from
both indexing and thumbnail generation:

- Runs a simple threshold + connected-component pass (background estimate via median,
  detect blobs above `background + k·stddev`, centroid + FWHM-style spread per blob) —
  deliberately simpler than the autofocus plugin's analyzer, since this only needs
  approximate numbers good enough to sort by, not focus-critical precision. It does
  **not** import from the autofocus plugin (plugins can't import each other); if the two
  ever want to share more precision, that goes through the event bus, not a direct import.
- Only runs for `frame_type == 'light'` — meaningless for calibration frames, so those
  rows keep `NULL` and are simply not sortable by quality.
- Processed a few frames at a time via a bounded queue, explicitly **not** competing with
  an active capture session — paused while any camera is exposing/looping (checked via
  `imager_manager.all_statuses()`), resumed when idle.
- `FrameTable` gains sortable `bg_median`/`star_count`/`hfr` columns — this is what
  "hunting for an outlier among 180 near-identical subs" actually needs; a sortable table
  beats a thumbnail wall for exactly this task.

## Filters

- Frame type (multi-select: light/dark/flat/bias)
- Date range
- Object name (text match)
- Filter name, camera name
- Quality range (once metrics exist): `star_count` / `hfr` min/max, for "show me the
  worst 10 subs in this group"
- **Coordinate proximity search** — `ra_deg`, `dec_deg`, `radius_deg`, for frames whose
  `object_name` is blank but a coordinate was recorded. A SQL bounding-box prefilter
  (`ra_deg` within `radius/cos(dec_deg)`, `dec_deg` within `radius`) narrows the candidate
  set, followed by an exact `astropy` `SkyCoord.separation` check — full spherical
  geometry isn't expressible directly in SQLite. The bounding box is **clamped to the
  full 0–360° RA range whenever `|dec_deg| + radius_deg ≥ 90`** (near either pole, a
  fixed-width RA box is nonsensical), and the RA window itself wraps correctly across the
  0°/360° seam.

## "Set as target"

Reuses the existing core `PUT /mount/{device_id}/target` — no new backend endpoint.
`source="viewer"`, `frame="icrs"`, `ra`/`dec` from the frame's resolved coordinate
(`coord_source`-aware conversion, see *Coordinates*), `name` = `object_name` if set.
Available on an individual frame (`ImageDetail`, and per-row in `FrameTable`) and on a
group row (using its representative frame's coordinates). Disabled with a tooltip when the
frame has no resolved coordinate.

Mount selection: **disabled** with a tooltip when no mount is connected; a **direct**
action when exactly one mount is connected; a small **picker** when more than one is
connected. The action only stores the target — it explicitly does **not** slew; the UI
button/tooltip says so, matching how the core `Target` model already behaves elsewhere.

## Destructive action: reject, not delete

The only destructive action in v1 is a **reject**, not a hard delete: the FITS file (and
its cache entries/index row) move to `<library_dir>/_rejected/<original-relative-path>`,
a folder the scanner excludes. This is reversible (move it back) while still solving the
real problem — pruning a bad sub out of a set of hundreds without a single irreversible
click. A separate, explicitly-labelled **"Empty rejected"** action in `SettingsPanel`
permanently deletes everything currently under `_rejected/`, with a confirmation dialog
and a count/size shown before confirming.

## Preview & stats API

Splitting these two (per the v0.2 review) matters because they don't actually depend on
the same inputs: the histogram itself is fixed per frame; only the stretch **clip
markers** depend on the user's black/white settings.

- `GET /plugins/viewer/images/{id}/stats` — computed once, cached (histogram, `bg_median`,
  etc. — independent of stretch settings).
- `GET /plugins/viewer/images/{id}/preview.jpg?mode=auto|linear&black=&white=&quality=` —
  a plain, browser-cacheable image endpoint (the query string is part of the cache key by
  construction, so no server-side cache is needed and there's no unbounded temp
  directory to garbage-collect). Generated directly into the HTTP response, not written
  to an intermediate `/cache/{filename}` path.

The frontend's `LabeledSlider` already only commits on release, not on every drag tick;
in addition, `ImageDetail` aborts any in-flight preview request when a new one is issued
(a full-resolution render can take seconds on a Pi, and a fast slider drag shouldn't queue
up several of them).

## Extras that fit the scope

- **Next/prev in `ImageDetail`** via arrow keys, keeping the current stretch settings
  across frames — this is the actual "blink review" workflow for triaging a set of subs,
  and costs almost nothing to add given the frame list is already paginated/filterable.
- **`GET /plugins/viewer/rollup?group_by=object`** — total integration time and frame
  count per object across all nights (shown in `RollupPanel.tsx`), the first question
  most imagers ask about their own library.
- **Disk usage**: `library_dir` total size and free space (`shutil.disk_usage`, cheap),
  shown in `SettingsPanel`/`RollupPanel` — SD cards fill up and this library only grows.
- A raw-FITS-header panel and a "download original FITS" link in `ImageDetail`.

## REST API (final shape)

```
GET/PUT /plugins/viewer/settings                     {library_dir}
POST    /plugins/viewer/rescan                        409 if already running
DELETE  /plugins/viewer/rescan                        cancel an in-flight rescan
GET     /plugins/viewer/facets                        distinct objects/frame_types/filters/cameras
GET     /plugins/viewer/rollup?group_by=object         per-object integration time + frame count
GET     /plugins/viewer/groups                        paginated, filtered — aggregated rows
GET     /plugins/viewer/images                        paginated, filtered — flat list; also how a
                                                        group is "expanded" (see Grouping)
GET     /plugins/viewer/images/{id}
GET     /plugins/viewer/images/{id}/thumbnail
GET     /plugins/viewer/images/{id}/stats
GET     /plugins/viewer/images/{id}/preview.jpg
GET     /plugins/viewer/images/{id}/fits              raw file download
POST    /plugins/viewer/images/{id}/reject
POST    /plugins/viewer/images/{id}/unreject
POST    /plugins/viewer/rejected/empty                 permanent delete of everything in _rejected/
```

Events: `viewer.index_changed` (server-debounced — a multi-frame rescan or an
`ExposureCompleted` burst coalesces into at most one emission per second, not one per
file), `viewer.rescan_started` / `viewer.rescan_progress` / `viewer.rescan_completed`.

## Testing

`plugins/viewer/tests/`, plus one `tests/unit/` case for the core `preview.py` addition:

- Indexer: correct header extraction; incremental rescan skips unchanged `(size, mtime)`,
  picks up changed ones, drops removed ones; the rescan/live-indexer race (generation
  guard — a row inserted mid-walk by the live indexer must survive that walk's delete
  step); single-flight rescan returns 409; cancellation cleans up.
- Coordinates: WCS priority over header RA/DEC; sexagesimal `OBJCTRA`/`OBJCTDEC` parsing;
  JNow + `EQUINOX` conversion; a frame with no resolvable coordinate leaves
  `coord_source == null` and disables "set as target".
- Grouping: each frame_type's key rules (flats ignoring exposure, bias keeping gain,
  darks ignoring night); the blank-object-name sky-cell fallback separating two distinct
  untracked pointings shot the same night; float-drift in exposure/gain not splitting a
  group.
- Night bucketing: a session crossing local midnight stays in one bucket; the `SITELONG`
  vs. system-timezone fallback.
- Coordinate search: the RA 0°/360° seam and a near-pole search both return correct
  candidates.
- `library_dir` change: purges out-of-root rows and garbage-collects orphaned thumbnails.
- Quality metrics: only computed for `frame_type == 'light'`; the background queue
  yields when a camera is exposing.
- API: list/filter/pagination (keyset) for both `/groups` and `/images`; stats vs. preview
  split; reject/unreject/empty-rejected lifecycle; core `fits_to_thumbnail` unit test.
