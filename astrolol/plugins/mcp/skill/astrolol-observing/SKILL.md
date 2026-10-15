---
name: astrolol-observing
description: Operate an astrolol telescope rig (mount, camera, focuser, filter wheel, guider, sequencer) through its MCP tools. Use when the user wants to point the telescope, take or check images, focus, guide, run an imaging sequence, or find out what the rig is doing.
---

# Observing with astrolol

You control a real telescope through the `astrolol` MCP tools. Hardware moves when you call
them, and nobody may be standing next to it. Work carefully, say what you are about to do, and
leave the rig safe.

If the tools are missing, the user has to add the server. In Claude Code:

```
claude mcp add --transport http astrolol http://<host>:8000/plugins/mcp --header "Authorization: Bearer <token>"
```

The header is only needed when the server asks for a sign-in (create a token on the Security page).

## Always start with `get_overview`

It shows the active profile, every connected device with live status, the guider, autofocus and
the sequencer. Use the device ids it lists (`mount_…`, `camera_…`) in the other tools. If nothing is
connected, `list_profiles` then `activate_profile` connects the rig.

## Units and coordinates

- Tool inputs take coordinates in **degrees**: `ra_deg` 0–360, `dec_deg` −90..90, ICRS (J2000).
- **Status values report RA in hours** (0–24) and Dec in degrees. Convert before comparing:
  `ra_deg = ra_hours × 15`.
- `search_objects` gives degrees, ready for `mount_slew` / `platesolve_center`.

## A normal night

1. `get_overview`; check the mount, camera temperature and that the sky is plausible.
2. `camera_set_cooler` on, with a set point; let it settle before long exposures.
3. `mount_unpark`, `mount_set_tracking`.
4. `search_objects` for the target, `target_visibility` to confirm it is up and when it transits.
5. `platesolve_center` to land on the target precisely (a plain `mount_slew` is only as good as the mount's alignment).
6. `autofocus_start` (after the filter and temperature are final), `guiding_start`, then poll `guiding_status` until it is guiding and not settling.
7. Image: either single `camera_expose` calls, or build a queue with `sequencer_add_task`, check it with `sequencer_preflight`, and run `sequencer_start`.
8. When finished: `guiding_stop`, `mount_park`, `camera_set_cooler` off (or warm up gradually).

## Safety rules

- Before any `mount_slew`, `mount_meridian_flip` or `mount_sync`: confirm the mount is unparked, the target is above the horizon (check `alt`, or `target_visibility`), and **stop guiding first**.
- Don't `mount_sync` unless you have a verified position (a successful `platesolve_here`). A wrong sync ruins the pointing model.
- Never start the sequencer without a clean `sequencer_preflight`. Tell the user what will run unattended.
- If something looks wrong (unexpected motion, errors piling up, weather), call `emergency_stop`, then explain.
- A slew, park or autofocus that returns `"result": "timeout"` is **not finished**: check `get_overview` or `mount_status`, don't assume.
- Ask the user before long or irreversible actions (starting a night's sequence, removing queue tasks, recalibrating the guider).
- Park the mount at the end of every session unless told otherwise.

## Reading results

- `camera_expose` returns file path, image statistics and a quick-look preview. Judge focus (star shape and size), tracking (trails) and exposure (is the background lifted off zero? is anything saturated?) from it. The preview is a stretch of the data, not the data.
- `autofocus_start` returns the sampled positions with FWHM. A clean V/U shape with the minimum inside the sweep is a good result. If the minimum sits at an edge, rerun with a wider sweep or a different start. `status: failed` with no stars means check the pointing and exposure time.
- `guiding_status`: RMS error is in arcseconds. Below about 1″ is good for most setups. Repeated star loss means clouds, a bad guide star, or a lost mount.
- `get_events` (filter with `type_prefix`, e.g. `sequencer`, `mount`) tells you why something stopped.

## The sequencer

`sequencer_task_schema` shows what a task looks like (target, lanes of exposures per filter, whether to slew, centre, guide, autofocus, dither, what to do on error). Build tasks from it, add them with `sequencer_add_task` (the server explains any mistake), preflight, start, then watch with `sequencer_status` and `sequencer_queue`. `sequencer_pause` / `sequencer_stop` end at a frame boundary by default so no frame is lost; progress is kept and a later `sequencer_start` resumes.

## When a tool fails

Errors come back as text starting with the HTTP status. `409` means the device is busy or in the wrong state (parked, already slewing, already exposing): read the state, don't just retry. `403` means your token's access level is too low (viewers can look but not operate). `404` on a device id means you used a wrong id: copy it from `list_devices`. For anything the tools don't cover, `api_get` reads any REST path (the API reference is at `/docs` on the server).
