"""Sky-Watcher motor controller command set (the protocol EQMOD/indi-eqmod speak).

Source: Sky-Watcher's "Motor Controller Command Set" (skywatcher.com, application
development downloads, rev. 2021-08-25). The controller only knows per-axis step
counts, timer presets and direction bits — all geometry lives in geometry.py.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol

POSITION_OFFSET = 0x800000
SIDEREAL_DEG_PER_SEC = 360.0 / 86164.0905
# Above this rate the doc says to switch the axis to high-speed mode (T1 fires N steps).
HIGH_SPEED_THRESHOLD_DEG_PER_SEC = 128 * SIDEREAL_DEG_PER_SEC

ERROR_CODES = {
    0x0: "Unknown command",
    0x1: "Command length error",
    0x2: "Motor not stopped",
    0x3: "Invalid character",
    0x4: "Not initialized",
    0x5: "Driver sleeping",
    0x7: "PEC training is running",
    0x8: "No valid PEC data",
}


class Axis(IntEnum):
    RA = 1
    DEC = 2
    BOTH = 3


class GuideRate(IntEnum):
    X1_00 = 0
    X0_75 = 1
    X0_50 = 2
    X0_25 = 3
    X0_125 = 4


class EqmodProtocolError(Exception):
    """Malformed, missing or unexpected data on the wire."""


class EqmodMountError(Exception):
    """The controller answered with a '!' error response."""

    def __init__(self, code: int) -> None:
        self.code = code
        super().__init__(f"Mount error {code:X}: {ERROR_CODES.get(code, 'unknown')}")


class Transport(Protocol):
    async def request(self, command: bytes) -> bytes: ...


# --- Encoding (byte order is little-endian, each byte written as two hex digits) ---

def encode_uint(value: int, bits: int) -> str:
    if bits not in (8, 16, 24):
        raise ValueError(f"Unsupported width: {bits}")
    if not 0 <= value < (1 << bits):
        raise ValueError(f"{value} does not fit in {bits} bits")
    return "".join(f"{(value >> shift) & 0xFF:02X}" for shift in range(0, bits, 8))


def decode_uint(data: str) -> int:
    if not data or len(data) % 2 or len(data) > 6:
        raise EqmodProtocolError(f"Bad numeric field: {data!r}")
    try:
        return sum(int(data[i:i + 2], 16) << (4 * i) for i in range(0, len(data), 2))
    except ValueError as exc:
        raise EqmodProtocolError(f"Bad numeric field: {data!r}") from exc


def encode_position(count: int) -> str:
    return encode_uint((count + POSITION_OFFSET) & 0xFFFFFF, 24)


def decode_position(data: str) -> int:
    return decode_uint(data) - POSITION_OFFSET


def build_command(cmd: str, axis: Axis | int, data: str = "") -> bytes:
    if len(cmd) != 1:
        raise ValueError(f"Command must be one character: {cmd!r}")
    return f":{cmd}{int(axis)}{data}\r".encode("ascii")


def parse_response(raw: bytes) -> str:
    text = raw.decode("ascii", errors="replace").rstrip("\r")
    if text.startswith("="):
        return text[1:]
    if text.startswith("!"):
        try:
            code = int(text[1:], 16) if text[1:] else -1
        except ValueError as exc:
            raise EqmodProtocolError(f"Bad error response: {raw!r}") from exc
        raise EqmodMountError(code)
    raise EqmodProtocolError(f"Unexpected response: {raw!r}")


@dataclass(frozen=True)
class AxisStatus:
    tracking_mode: bool   # False = GOTO mode
    ccw: bool
    fast: bool
    running: bool
    blocked: bool
    initialized: bool
    level_switch: bool


def parse_status(data: str) -> AxisStatus:
    if len(data) != 3:
        raise EqmodProtocolError(f"Bad status field: {data!r}")
    try:
        n0, n1, n2 = (int(c, 16) for c in data)
    except ValueError as exc:
        raise EqmodProtocolError(f"Bad status field: {data!r}") from exc
    return AxisStatus(
        tracking_mode=bool(n0 & 1),
        ccw=bool(n0 & 2),
        fast=bool(n0 & 4),
        running=bool(n1 & 1),
        blocked=bool(n1 & 2),
        initialized=bool(n2 & 1),
        level_switch=bool(n2 & 2),
    )


def encode_motion_mode(*, tracking: bool, fast: bool, ccw: bool) -> str:
    # DB1 bit1 means "fast" in tracking mode but "slow" in GOTO mode.
    db1 = 1 if tracking else 0
    if tracking == fast:
        db1 |= 2
    db2 = 1 if ccw else 0
    return f"{db1:X}{db2:X}"


def step_period_for_rate(
    deg_per_sec: float, cpr: int, timer_freq: int, high_speed_ratio: int = 1
) -> int:
    """T1 preset for a speed, per the doc's formula; pass the high-speed ratio N in fast mode."""
    if deg_per_sec <= 0:
        raise ValueError("Rate must be positive")
    period = math.floor(high_speed_ratio * timer_freq * 360.0 / deg_per_sec / cpr)
    # Out of range means the rate is unachievable in this mode — never clamp to a wrong speed.
    if period < 1:
        raise ValueError(f"{deg_per_sec} deg/s is too fast for this mode; use high-speed mode")
    if period > 0xFFFFFF:
        raise ValueError(f"{deg_per_sec} deg/s is too slow for this mode")
    return period


class SkywatcherProtocol:
    """One method per command astrolol uses; all I/O goes through the injected transport."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def _cmd(self, cmd: str, axis: Axis | int, data: str = "") -> str:
        return parse_response(await self._transport.request(build_command(cmd, axis, data)))

    # --- Inquiries ---

    async def inquire_motor_board_version(self) -> int:
        return decode_uint(await self._cmd("e", Axis.RA))

    async def inquire_cpr(self, axis: Axis) -> int:
        return decode_uint(await self._cmd("a", axis))

    async def inquire_timer_freq(self) -> int:
        return decode_uint(await self._cmd("b", Axis.RA))

    async def inquire_high_speed_ratio(self, axis: Axis) -> int:
        return decode_uint(await self._cmd("g", axis))

    async def inquire_position(self, axis: Axis) -> int:
        return decode_position(await self._cmd("j", axis))

    async def inquire_goto_target(self, axis: Axis) -> int:
        return decode_position(await self._cmd("h", axis))

    async def inquire_step_period(self, axis: Axis) -> int:
        return decode_uint(await self._cmd("i", axis))

    async def inquire_status(self, axis: Axis) -> AxisStatus:
        return parse_status(await self._cmd("f", axis))

    async def inquire_extended_status(self, axis: Axis) -> str:
        """Raw 6-digit feature flags (dual encoder, original position indexer, polar LED, …)."""
        return await self._cmd("q", axis, encode_uint(1, 24))

    # --- Settings / motion ---

    async def initialize(self, axis: Axis = Axis.BOTH) -> None:
        await self._cmd("F", axis)

    async def set_motion_mode(self, axis: Axis, *, tracking: bool, fast: bool, ccw: bool) -> None:
        await self._cmd("G", axis, encode_motion_mode(tracking=tracking, fast=fast, ccw=ccw))

    async def set_goto_target(self, axis: Axis, position: int) -> None:
        await self._cmd("S", axis, encode_position(position))

    async def set_goto_target_increment(self, axis: Axis, counts: int) -> None:
        await self._cmd("H", axis, encode_uint(counts, 24))

    async def set_step_period(self, axis: Axis, period: int) -> None:
        await self._cmd("I", axis, encode_uint(period, 24))

    async def set_position(self, axis: Axis, position: int) -> None:
        await self._cmd("E", axis, encode_position(position))

    async def start_motion(self, axis: Axis) -> None:
        await self._cmd("J", axis)

    async def stop_motion(self, axis: Axis) -> None:
        await self._cmd("K", axis)

    async def instant_stop(self, axis: Axis) -> None:
        await self._cmd("L", axis)

    async def set_polar_led_brightness(self, level: int) -> None:
        await self._cmd("V", Axis.RA, encode_uint(level, 8))

    async def set_autoguide_speed(self, axis: Axis, rate: GuideRate) -> None:
        await self._cmd("P", axis, str(int(rate)))
