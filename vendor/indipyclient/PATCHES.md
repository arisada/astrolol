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
