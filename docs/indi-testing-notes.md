# INDI Simulator Testing — Bugs and Gotchas

Notes from writing and debugging `tests/integration/test_indi_simulators.py` against
`indi-bin 2.2.0` simulators (`indi_simulator_telescope`, `indi_simulator_focus`,
`indi_simulator_ccd`).

---

## 1. Initial property dump race condition

**Symptom:** A command sent immediately after `connect_device()` appears to go BUSY, but
then the wait returns in <1 ms claiming the operation is done, and nothing actually happened.

**Root cause:** After `CONNECTION=ON` is set, the INDI server continues sending
`defXxxVector` messages for all device-specific properties. Each of these arrives with
`state=OK` (the current/default state). If a command is sent before this flood finishes,
the late OK-state property definition overwrites the BUSY update that acknowledged the
command. Any code waiting on `state != BUSY` then sees OK immediately and exits.

**Fix:** After `wait_for_connection_on`, add a "settle" phase that waits until no property
update arrives for ~150 ms. This indicates the initial dump is complete.

```python
# Phase 2 of wait_for_connection_on — wait for the property dump to drain
settle_deadline = time.monotonic() + 0.15
with self._updated:
    while True:
        remaining = settle_deadline - time.monotonic()
        if remaining <= 0:
            return
        notified = self._updated.wait(timeout=remaining)
        if notified:
            settle_deadline = time.monotonic() + 0.15  # reset on any update
```

---

## 2. `wait_prop_not_busy` exits before the operation starts

**Symptom:** Move/slew commands appear to complete instantly, but the device hasn't moved.

**Root cause:** `wait_prop_not_busy` checks the current property state and returns if it
is not BUSY. If called before the server has had time to set the property to BUSY (the
command is still in flight), it sees `state=OK` and exits immediately — never waiting for
the operation at all.

**Fix:** Use a two-phase wait:
1. **Phase 1** — wait for the property to enter BUSY (up to a short `busy_timeout`, e.g.
   2 s). If it never goes BUSY, the command was instantaneous and we can return.
2. **Phase 2** — wait for BUSY to end (the operation completed).

This is `wait_prop_busy_then_done` in `_SyncIndiClient`.

---

## 3. INDI focuser simulator: inward relative moves never complete

**Symptom:** `test_focuser_move_by_negative` hangs for 60 s then times out.

**Root cause:** In `indi_simulator_focus` (indi-bin 2.2.0), setting
`REL_FOCUS_POSITION` with `FOCUS_INWARD` puts the property into BUSY and it never
transitions back to OK. Outward relative moves (`FOCUS_OUTWARD`) work fine.

**Fix:** Implement `move_by` as an absolute move: read the current
`ABS_FOCUS_POSITION`, compute the target, and set `ABS_FOCUS_POSITION` directly.
This avoids the REL property entirely.

---

## 4. `wait_for_switch_on` returns mid-operation (BUSY state has the element ON)

**Symptom:** `park()` returns before parking is complete. `unpark()` is then called while
the mount is still moving to the park position, and the UNPARK command is silently
ignored. The test then times out waiting for unpark to complete.

**Root cause:** When the INDI telescope simulator receives the PARK command, it sets
`TELESCOPE_PARK` to `state=BUSY, PARK=ON, UNPARK=OFF` as an acknowledgment. A
polling approach that only checks if the PARK element is `ISS_ON` will see it as ON at
the moment of acknowledgment — before the actual slew to the park position has begun.

**Fix:** Use `wait_prop_busy_then_done("TELESCOPE_PARK")` for both `park()` and
`unpark()`. This correctly waits for BUSY to end, not just for an element to appear in
a particular state.

---

## 5. TELESCOPE_PARK: UNPARK element is not latched after unparking

**Symptom:** Polling for `TELESCOPE_PARK/UNPARK == ISS_ON` after sending an UNPARK
command times out.

**Root cause:** After the mount finishes unparking, the simulator sets
`TELESCOPE_PARK` to `state=OK, PARK=OFF, UNPARK=OFF`. Neither element is ON after
the operation — they are momentary-action switches, not latched state switches. The
PARK element is ON only while the mount is in the parked state; UNPARK is never
persistently ON.

**Implication:** Do not use `wait_for_switch_on(element="UNPARK")` after an unpark
command. Use `wait_prop_busy_then_done` (which waits for the BUSY→OK transition) or
`wait_for_switch_off(element="PARK")`.

---

## 6. Slew commands are silently ignored when the mount is parked

**Symptom:** After connecting to the telescope simulator (which starts in a parked
state), calling `slew()` sends `EQUATORIAL_EOD_COORD`, the property briefly goes BUSY
then OK, but the mount position does not change.

**Root cause:** Most INDI telescope drivers (including the simulator) ignore slew
commands when the mount is parked. The driver acknowledges the property update (goes
BUSY) but does not actually move.

**Fix:** `IndiMount.slew()` now reads the current TELESCOPE_PARK/PARK state before
slewing and calls `unpark()` first if the mount is parked.

---

## 7. PyIndi segfault at process exit

**Symptom:** After all tests pass, the process exits with `Fatal Python error:
Segmentation fault` and a C++ backtrace inside PyIndi.

**Root cause:** PyIndi starts a C++ receiver thread when `connectServer()` is called.
Calling `disconnectServer()` while callbacks are still in flight can cause a use-after-free.
At process exit, Python tears down objects in an unpredictable order which sometimes races
with the receiver thread.

**Workaround:** Do NOT call `disconnectServer()` in `IndiClient.disconnect()`. Instead,
set `_active = False` (so all callbacks become no-ops) and let the TCP EOF from killing
the indiserver process terminate the receiver thread naturally. The segfault is benign —
it only occurs after all tests have completed and does not affect exit code or results.

---

## 8. Only one indiserver per host (abstract Unix socket conflict)

**Symptom:** Starting a second `indiserver` process fails or the first one crashes.

**Root cause:** `indiserver` binds an abstract Unix socket (`@/tmp/indiserver`) in
addition to its TCP port. Only one instance can bind this socket on a given host at
a time, regardless of which TCP port is used.

**Fix:** Load all required simulator drivers into a single shared `indiserver` instance.
Use a module-scoped pytest fixture (`_shared_server`) for the process, and separate
module-scoped client fixtures (one per device type) so each device gets its own
`_SyncIndiClient` connection.
