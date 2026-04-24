# Local patches on top of indipyclient 0.9.1

## Fix O(n²) bytes accumulation in `_datainput` and `_xmlinput`

**Files**: `indipyclient/ipyclient.py`

**Problem**: `_datainput` accumulates TCP chunks into `binarydata` using `bytes +=
bytes`. Python `bytes` is immutable, so each `+=` allocates a fresh buffer and
copies the entire accumulated payload. For a 50 MB BLOB split into ~1 550 chunks
of 32 kB each (via `LimitOverrunError` fallback), this is O(n²) in total bytes
copied — roughly 39 GB of memcpy on a Raspberry Pi 4. The asyncio event loop is
blocked for several seconds per exposure, causing task-late warnings and making
the exposure detection appear to time out.

`_xmlinput` had the same pattern for its `message` accumulation buffer.

**Fix**: Replace `b""` with `bytearray()` in both functions. `bytearray` supports
in-place append in O(1) amortised time. All downstream operations (`startswith`,
`endswith`, `in`, `strip`, `decode`) accept `bytearray` transparently.

**Upstream PR**: pending — submit to https://github.com/bernie-skipole/indipyclient

## Fix `setBLOBVector` parsing in UPLOAD_LOCAL mode

**Files**: `indipyclient/events.py`

**Problem**: When an INDI CCD driver is configured with `UPLOAD_MODE=UPLOAD_LOCAL`, it writes
the FITS file directly to disk and sends a `setBLOBVector` with `size=0` and the file path
as the element text instead of base64-encoded image data. The original code unconditionally
called `standard_b64decode` on the element text, causing a `ParseException` because a file
path is not valid base64.

**Fix**: Check `membersize == 0` before attempting base64 decoding. When size is zero, store
the element text (the file path) as raw bytes so callers can detect local-upload mode via the
zero size and extract the path from the member value.

**Upstream PR**: pending — submit to https://github.com/bernie-skipole/indipyclient
