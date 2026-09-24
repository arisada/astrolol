"""Tests for the Sky-Watcher motor controller protocol layer (no hardware)."""
from __future__ import annotations

import pytest

from plugins.eqmod.protocol import (
    POSITION_OFFSET,
    SIDEREAL_DEG_PER_SEC,
    Axis,
    EqmodMountError,
    EqmodProtocolError,
    GuideRate,
    SkywatcherProtocol,
    build_command,
    decode_position,
    decode_uint,
    encode_motion_mode,
    encode_position,
    encode_uint,
    parse_response,
    parse_status,
    step_period_for_rate,
)


# --- Byte order: the doc's own worked examples ---

@pytest.mark.parametrize("value,bits,expected", [
    (0x123456, 24, "563412"),
    (0x1234, 16, "3412"),
    (0x12, 8, "12"),
    (0, 24, "000000"),
    (0xFFFFFF, 24, "FFFFFF"),
])
def test_encode_uint_matches_doc_examples(value: int, bits: int, expected: str) -> None:
    assert encode_uint(value, bits) == expected


@pytest.mark.parametrize("data,expected", [
    ("563412", 0x123456),
    ("3412", 0x1234),
    ("12", 0x12),
])
def test_decode_uint_matches_doc_examples(data: str, expected: int) -> None:
    assert decode_uint(data) == expected


@pytest.mark.parametrize("value", [0, 1, 0xABCDEF, 0x800000, 0xFFFFFF])
def test_uint_roundtrip(value: int) -> None:
    assert decode_uint(encode_uint(value, 24)) == value


def test_encode_uint_rejects_overflow() -> None:
    with pytest.raises(ValueError):
        encode_uint(0x1000000, 24)
    with pytest.raises(ValueError):
        encode_uint(-1, 24)


@pytest.mark.parametrize("data", ["", "1", "12345", "1234567Z", "GG"])
def test_decode_uint_rejects_garbage(data: str) -> None:
    with pytest.raises(EqmodProtocolError):
        decode_uint(data)


# --- Position offset: the doc's other worked example ---

def test_position_offset_matches_doc_example() -> None:
    # Doc: true position 0x000012 is sent as 0x800012; reported 0x801234 means 0x001234.
    assert encode_position(0x12) == encode_uint(0x800012, 24)
    assert decode_position(encode_uint(0x801234, 24)) == 0x1234


@pytest.mark.parametrize("count", [0, 1, -1, 1_000_000, -1_000_000])
def test_position_roundtrip_including_negative(count: int) -> None:
    assert decode_position(encode_position(count)) == count


def test_position_zero_is_offset_on_the_wire() -> None:
    assert decode_uint(encode_position(0)) == POSITION_OFFSET


# --- Framing ---

def test_build_command() -> None:
    assert build_command("e", Axis.RA) == b":e1\r"
    assert build_command("F", Axis.BOTH) == b":F3\r"
    assert build_command("S", Axis.DEC, "563412") == b":S2563412\r"


def test_parse_response_normal() -> None:
    assert parse_response(b"=563412\r") == "563412"
    assert parse_response(b"=\r") == ""


def test_parse_response_error_carries_code() -> None:
    with pytest.raises(EqmodMountError) as exc_info:
        parse_response(b"!2\r")
    assert exc_info.value.code == 2
    assert "Motor not stopped" in str(exc_info.value)


@pytest.mark.parametrize("raw", [b"", b"563412\r", b"?\r", b"!ZZ\r"])
def test_parse_response_rejects_malformed(raw: bytes) -> None:
    with pytest.raises(EqmodProtocolError):
        parse_response(raw)


# --- Status and motion mode bitfields ---

def test_parse_status_all_clear() -> None:
    s = parse_status("000")
    assert (s.tracking_mode, s.ccw, s.fast, s.running, s.blocked, s.initialized, s.level_switch) == (
        False, False, False, False, False, False, False,
    )


def test_parse_status_bits() -> None:
    s = parse_status("713")
    assert s.tracking_mode and s.ccw and s.fast
    assert s.running and not s.blocked
    assert s.initialized and s.level_switch


@pytest.mark.parametrize("data", ["", "00", "0000", "0G0"])
def test_parse_status_rejects_malformed(data: str) -> None:
    with pytest.raises(EqmodProtocolError):
        parse_status(data)


@pytest.mark.parametrize("tracking,fast,ccw,expected", [
    (True, False, False, "10"),   # slow tracking, CW
    (True, True, False, "30"),    # fast tracking: bit1 = fast
    (False, True, False, "00"),   # fast GOTO: bit1 = 0
    (False, False, True, "21"),   # slow GOTO: bit1 = slow, CCW
])
def test_encode_motion_mode_inverted_speed_bit(tracking: bool, fast: bool, ccw: bool, expected: str) -> None:
    assert encode_motion_mode(tracking=tracking, fast=fast, ccw=ccw) == expected


# --- Speed formula (doc section 3) ---

def test_step_period_for_sidereal_rate() -> None:
    cpr, timer_freq = 9_024_000, 64_935  # plausible values; formula is what's under test
    period = step_period_for_rate(SIDEREAL_DEG_PER_SEC, cpr, timer_freq)
    assert period == int(timer_freq * 360.0 / SIDEREAL_DEG_PER_SEC / cpr)


def test_step_period_high_speed_scales_by_ratio() -> None:
    slow = step_period_for_rate(0.5, 9_024_000, 64_935, high_speed_ratio=1)
    fast = step_period_for_rate(0.5, 9_024_000, 64_935, high_speed_ratio=16)
    assert 16 * slow <= fast <= 16 * slow + 15  # floor() applied after scaling


def test_step_period_refuses_rates_unachievable_in_slow_mode() -> None:
    # 3 deg/s needs a preset below 1 in slow mode; only high-speed mode can do it.
    with pytest.raises(ValueError, match="high-speed"):
        step_period_for_rate(3.0, 9_024_000, 64_935)
    assert step_period_for_rate(3.0, 9_024_000, 64_935, high_speed_ratio=16) >= 1


def test_step_period_rejects_non_positive_rate() -> None:
    with pytest.raises(ValueError):
        step_period_for_rate(0.0, 9_024_000, 64_935)


# --- Command API over a fake transport ---

class _FakeTransport:
    def __init__(self, responses: dict[bytes, bytes]) -> None:
        self.responses = responses
        self.sent: list[bytes] = []

    async def request(self, command: bytes) -> bytes:
        self.sent.append(command)
        return self.responses.get(command, b"!0\r")


async def test_inquiries_decode_responses() -> None:
    t = _FakeTransport({
        b":a1\r": b"=" + encode_uint(9_024_000, 24).encode() + b"\r",
        b":b1\r": b"=" + encode_uint(64_935, 24).encode() + b"\r",
        b":g2\r": b"=10\r",
        b":j2\r": b"=" + encode_position(-1234).encode() + b"\r",
        b":f1\r": b"=111\r",
    })
    p = SkywatcherProtocol(t)
    assert await p.inquire_cpr(Axis.RA) == 9_024_000
    assert await p.inquire_timer_freq() == 64_935
    assert await p.inquire_high_speed_ratio(Axis.DEC) == 0x10
    assert await p.inquire_position(Axis.DEC) == -1234
    status = await p.inquire_status(Axis.RA)
    assert status.tracking_mode and status.running and status.initialized


async def test_commands_are_encoded_on_the_wire() -> None:
    t = _FakeTransport({})
    t.responses = {cmd: b"=\r" for cmd in [
        b":F3\r",
        b":G110\r",
        b":S2" + encode_position(1000).encode() + b"\r",
        b":I1" + encode_uint(1234, 24).encode() + b"\r",
        b":J1\r",
        b":K2\r",
        b":L1\r",
        b":E1" + encode_position(-5).encode() + b"\r",
        b":V1" + encode_uint(0x80, 8).encode() + b"\r",
        b":P12\r",
    ]}
    p = SkywatcherProtocol(t)
    await p.initialize()
    await p.set_motion_mode(Axis.RA, tracking=True, fast=False, ccw=False)
    await p.set_goto_target(Axis.DEC, 1000)
    await p.set_step_period(Axis.RA, 1234)
    await p.start_motion(Axis.RA)
    await p.stop_motion(Axis.DEC)
    await p.instant_stop(Axis.RA)
    await p.set_position(Axis.RA, -5)
    await p.set_polar_led_brightness(0x80)
    await p.set_autoguide_speed(Axis.RA, GuideRate.X0_50)
    assert len(t.sent) == 10


async def test_extended_status_uses_encoded_inquiry_id() -> None:
    t = _FakeTransport({b":q1010000\r": b"=ABCDEF\r"})
    assert await SkywatcherProtocol(t).inquire_extended_status(Axis.RA) == "ABCDEF"


async def test_mount_error_propagates() -> None:
    t = _FakeTransport({b":J1\r": b"!4\r"})
    with pytest.raises(EqmodMountError) as exc_info:
        await SkywatcherProtocol(t).start_motion(Axis.RA)
    assert exc_info.value.code == 4
