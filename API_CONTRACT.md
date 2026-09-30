# astrolol client/server contract

This document describes what a client — the web UI, the Android shell app, or anything
else — may rely on when talking to an astrolol server. It is generated from the actual
models and endpoints in this repository, not aspirational. Sections 1–4 describe what
exists today; section 5 lists proposals that are not built yet. If this document and the
code disagree, the code is right and this document is stale — file that as a bug.

Changing anything in sections 1–4 requires updating any client's compatibility table
(the Android app's in particular). There is no automated check for that from astrolol's
side; treat this document as the thing a reviewer diffs against when an event model or
endpoint changes.

## 1. Protocol version and compatibility rules

`astrolol/version.py` defines a single integer, `PROTOCOL_VERSION` (currently `1`),
returned as `protocol_version` by `GET /health` (see §2).

- **Additive changes never bump it**: a new event type, a new optional field on an
  existing event, a new endpoint.
- **Breaking changes always bump it**: removing or renaming a field, changing what a
  field means, removing an endpoint or event type.
- **Client obligation**: ignore unknown event `type`s and unknown fields on known
  events. A client that doesn't do this will break the first time an unrelated plugin
  or feature adds something new.
- **Deprecation**: no formal policy exists yet beyond "don't do it without bumping the
  version." Revisit once there's a second protocol version to compare against.

## 2. Endpoints a client may rely on

### `GET /health`

```json
{
  "status": "ok",
  "protocol_version": 1,
  "server_version": "0.1.0",
  "enabled_plugins": ["hello", "phd2", "sequencer", "..."]
}
```

- `server_version` comes from installed package metadata (`importlib.metadata.version
  ("astrolol")`), not a hand-maintained string — it always matches what's actually
  running.
- `enabled_plugins` is the live, resolved set of plugin ids (including plugins
  auto-enabled as a dependency of another), not what's persisted in settings. A plugin
  appearing here doesn't guarantee its routes are reachable if it was hot-enabled while
  the built UI is being served — see the SPA-fallback route-ordering bug in `TODO.md`.
  Client "is the server too old" checks should compare `protocol_version`, not this list.

### `WS /ws/events`

The server pushes one JSON-encoded event object per text frame, oldest-thing-that-
happened first. The client sends nothing; there is no client → server message on this
socket. See §3 for the envelope shape and §4 for which event types exist.

### `GET /events/history`

Returns the last `HISTORY_SIZE` (10,000, `astrolol/core/events/bus.py`) events as a JSON
array, oldest first. This is an in-memory ring buffer — **it is lost on every server
restart**, including a restart triggered by `POST /admin/restart`. A reconnecting client
should fetch this, then subscribe to `/ws/events`, and de-duplicate on `id` (see §3) —
overlap between what history returns and what the socket then delivers is expected, not
a bug.

### Same-origin assumption

The web UI is served from `/` by the same process (`astrolol/api/static.py`); in
production there is no separate origin, no CORS headers, and none are needed. A client
that talks to the API from a different origin (e.g. the Android app hitting a bare IP)
must use absolute URLs itself — astrolol never issues absolute URLs or redirects that
would need proxy rewriting.

## 3. The event envelope

Every event (`astrolol/core/events/models.py::BaseEvent`) carries:

| Field | Type | Notes |
|---|---|---|
| `id` | string | UUID4. Stable across reconnects and history replay — the de-duplication key. |
| `timestamp` | string | ISO-8601 UTC. |
| `type` | string | Dotted, e.g. `sequencer.task_stalled`. The discriminator; see §4. |
| `notify` | `"info" \| "warning" \| "critical"` \| absent | See below. |
| `notify_title` | string \| absent | Set only alongside `notify`. |
| `notify_body` | string \| absent | Set only alongside `notify`. |

**The event catalog is not fixed.** Every plugin defines its own event classes; a type
like `phd2.guide_step` only ever appears if the `phd2` plugin is enabled (check
`GET /health`'s `enabled_plugins`, or `GET /plugins`). Don't hardcode an assumption that
a given plugin's events exist.

**`notify` is per-instance, not per-type.** The same event class can be published with
or without `notify` depending on who triggered it — for example `mount.parked` carries
`notify` when the automation loop parked the mount unattended, but not when a user
clicked "park" and is already looking at the result. A client must not treat "the type
is in some alert list" as sufficient; it must check whether `notify` is present on the
specific instance. Absent (the common case) means "not notify-worthy" — no severity, no
title, no body; ignore it and move on.

**Ordering**: history is ordered; the live stream is roughly ordered (single asyncio
queue per subscriber, so ordering holds per-connection). A reconnecting client should
expect overlap between the tail of history and the start of the live stream, and
de-duplicate on `id`.

## 4. Where `notify` is actually set today

This is deliberately short — most events never carry `notify`. Sources, as of this
writing:

| Type | When it notifies | Severity |
|---|---|---|
| `mount.parked` | Auto-park or horizon-limit park (not a user-requested park) | info |
| `mount.meridian_flip_completed` | Auto-flip only | info |
| `mount.operation_failed` (`operation="park"` or `"meridian_flip"`) | Automation-triggered attempt failed | warning |
| `mount.tracking_changed` | Horizon limit stopped tracking automatically | warning |
| `sequencer.session_finished` | Any run ending — `outcome="completed"` → info, `outcome="failed"` → warning; `stopped`/`cancelled` (user-requested) never notify | info / warning |
| `sequencer.step_failed` | Only when `handling="pause"` (the run is now blocked waiting on a human) | warning |
| `sequencer.interruption` | Only `kind="defer"` (a persistent error set the task aside) | warning |
| `sequencer.task_stalled` | Once per stall onset (not per retry — see `sequencer.stall_attempt`, which never notifies) | warning |
| `sequencer.task_unstalled` | Once per recovery | info |
| `guiding.state_changed` (`guiding=false`) | Star lost or guider disconnected, detected by the guider's own background loop — never for a guide/dither call a client made itself | warning |

Everything else — device connect/disconnect, exposures, slews, filter changes, all
`sequencer.step_*`/`frame_*`/`queue_changed` bookkeeping, `platesolve.*`, `autofocus.*`,
`viewer.*`, high-frequency position/coordinate updates — never carries `notify`. A
client that wants a live activity feed still gets all of these on `/ws/events`; it's
just that none of them are marked as "surface this to a human."

**Known gap**: `guiding.settled` (published after a guide/dither call settles or times
out) is not wired, because the underlying call is made both from a direct API request
and from the sequencer's background run loop, and nothing currently distinguishes which
one triggered a given settle — the same ambiguity `mount.park()`/`meridian_flip()` had
before they gained a `source` parameter. Left out rather than guessed at.

## 5. Proposals — not built

Nothing below exists yet. Don't write client code against it.

- **Auth token** — a bearer token for `GET`/`POST` (Authorization header) and
  `/ws/events` (query param or subprotocol, since a browser WebSocket handshake can't
  set arbitrary headers); must survive a reverse proxy injecting it. Required before any
  internet exposure. Tracked in `TODO.md`.
- **mDNS discovery** — advertising the server on the local network via `zeroconf` so the
  Android app doesn't need a typed-in IP. Tracked in `TODO.md`.
- **Absence-based notifications** — "autofocus should have run by now and didn't." Needs
  something watching a clock, not reacting to events; ties into the mount watchdog item
  in `TODO.md`. Not designed.
- **`guiding.settled` notify** — once the same-caller-ambiguity problem has a general
  answer (or gets solved ad hoc for the guiding plugins the way it was for the mount
  manager).

## 6. Change process

Any change to §1–4 must be reflected here in the same change, and checked against the
Android app's compatibility table. There is no contract test yet asserting the envelope
fields or the catalogued behavior in §4 — a reasonable follow-up would be
`tests/unit/test_api_contract.py` asserting `BaseEvent`'s fields and spot-checking a few
of the table's rows so an accidental rename fails a test instead of silently breaking
a client in the field.
