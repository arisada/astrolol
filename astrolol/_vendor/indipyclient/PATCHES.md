# Local patches on top of indipyclient 0.9.3

Upstream: https://github.com/bernie-skipole/indipyclient (PyPI: `indipyclient`).
This directory is the `indipyclient/` package of the 0.9.3 sdist, plus its LICENSE (MIT) and
the patches below. It lives inside astrolol (imported as `astrolol._vendor.indipyclient`)
because indipyclient is in neither Debian nor Ubuntu, so the `.deb` has to bring it along, and
PyPI refuses a dependency on a local directory. Once upstream has released all the patches,
replace the files with the unmodified release (and keep it here for the `.deb`, or package it
separately).

To re-vendor a newer release: copy the `indipyclient/` package of its sdist over this
directory (keep LICENSE up to date and this file), re-apply the patches still needed, and
update this document.

## 1. Parse the receive stream with `XMLPullParser` (`ipyclient.py`)

**Problem**: `_datainput` accumulated TCP chunks into `binarydata` with `bytes += bytes`.
`bytes` is immutable, so every `+=` copies the whole accumulated payload. A 50 MB BLOB
split into about 1 550 chunks of 32 kB is O(n²) in total bytes copied (roughly 39 GB of
memcpy on a Raspberry Pi 4). The asyncio event loop is blocked for several seconds per
exposure, causing task-late warnings and making exposure detection appear to time out.
`_xmlinput` had the same pattern for its message buffer.

**Fix**: `_run_rx` reads chunks from the stream and feeds them to an
`xml.etree.ElementTree.XMLPullParser`, so nothing is accumulated in Python. The stream
is wrapped in a synthetic `<root>` element, because INDI sends a sequence of top-level
elements with no document root; an "end" event that brings the depth back to 1 marks a
complete message. Each finished element is removed from the root so memory stays bounded.
A parse error logs an error and starts a fresh parser instead of ending the connection.
`_xmlinput`, `_datainput`, `_STARTTAGS` and `_ENDTAGS` are removed, since nothing uses them
any more. Upstream 0.9.2/0.9.3 changed `us-ascii` to `utf-8` in `_xmlinput`; the pull
parser reads bytes and defaults to UTF-8, so that change is covered.

## 2. Accept `newSwitchVector` / `newTextVector` / `newNumberVector` from the server (`events.py`)

**Problem**: these tags are normally client-to-server commands, but some INDI servers echo
them back to connected clients, and they were dropped as unrecognised tags, so the local
property state was not updated.

**Fix**: three subclasses (`newSwitchVector(setSwitchVector)` and so on) treat them like
their `set*` counterparts.

## 3. A set vector without `timeout` no longer drops the connection (`propertyvectors.py`)

**Problem**: `timeout` is optional on `set*Vector`, and INDIGO servers never send it. The
parsed event then has `timeout = None`, and `PropertyVector._setvector` copied it into the
vector. The next time the client sent that vector (a new exposure, a focuser move), its
timer started and `checktimedout` compared `None` with `vector_timeout_max`: the
`TypeError` ended `_check_alive`, which closed the connection. Whatever was in flight was
lost (an exposure waited for a BLOB that never came). Still in 0.9.4.

**Fix**: `_setvector` only takes the event's timeout when there is one, and `checktimedout`
treats a missing timeout as 0 (so the client's minimum applies).

