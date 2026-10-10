# Local patches on top of indipyclient 0.9.3

Upstream: https://github.com/bernie-skipole/indipyclient (PyPI: `indipyclient`).
This directory is the 0.9.3 sdist plus the three patches below. None of them is
merged upstream yet. Once they are, drop this directory and depend on the PyPI release.

To re-vendor a newer release: unpack its sdist over this directory (keep this file),
re-apply the patches, and update this document.

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

## 3. Fix `setBLOBVector` parsing in UPLOAD_LOCAL mode (`events.py`)

**Problem**: with an INDI CCD driver in `UPLOAD_MODE=UPLOAD_LOCAL`, the driver writes the
FITS file to disk and sends a `setBLOBVector` with `size=0` and the file path as the element
text instead of base64 data. The original code always called `standard_b64decode`, which
raised `ParseException` because a path is not valid base64.

**Fix**: when `membersize == 0`, store the element text (the path) as raw bytes, so callers
can detect local-upload mode by the zero size and read the path from the member value.
