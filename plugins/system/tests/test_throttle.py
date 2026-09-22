"""Tests for the throttling-detection module and periodic monitor."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from structlog.testing import capture_logs

from plugins.system.throttle import ThrottleMonitor, _parse_bits, get_throttle_status


# ── Bit parsing ────────────────────────────────────────────────────────────────

def test_parse_bits_all_clear() -> None:
    status = _parse_bits("0x0")
    assert status.underpowered is False
    assert status.under_voltage is False
    assert status.throttled is False
    assert status.freq_capped is False
    assert status.soft_temp_limit is False
    assert status.under_voltage_occurred is False


def test_parse_bits_under_voltage_now() -> None:
    status = _parse_bits("0x1")
    assert status.under_voltage is True
    assert status.underpowered is True
    assert status.throttled is False


def test_parse_bits_combined() -> None:
    # under-voltage now (bit 0) + throttled now (bit 2) + under-voltage occurred (bit 16)
    status = _parse_bits(hex((1 << 0) | (1 << 2) | (1 << 16)))
    assert status.under_voltage is True
    assert status.throttled is True
    assert status.under_voltage_occurred is True
    assert status.freq_capped is False
    assert status.underpowered is True


def test_parse_bits_only_occurred_flags_not_underpowered() -> None:
    # Issues happened since boot but nothing is wrong right now.
    status = _parse_bits(hex((1 << 16) | (1 << 18)))
    assert status.underpowered is False
    assert status.under_voltage_occurred is True
    assert status.throttled_occurred is True


def test_parse_bits_invalid_hex_defaults_to_clear() -> None:
    status = _parse_bits("not-hex")
    assert status.underpowered is False


# ── get_throttle_status: vcgencmd path ──────────────────────────────────────────

async def test_get_throttle_status_prefers_sysfs() -> None:
    """sysfs is a plain file read; vcgencmd pays fork/exec — sysfs should win when both work."""
    fake_path = MagicMock()
    fake_path.read_text.return_value = "0x8\n"  # bit 3 = soft temp limit active

    with patch("asyncio.create_subprocess_exec", AsyncMock()) as mock_exec:
        with patch("plugins.system.throttle._find_sysfs_path", return_value=fake_path):
            status = await get_throttle_status()

    assert status.available is True
    assert status.source == "sysfs"
    assert status.soft_temp_limit is True
    assert status.underpowered is True
    mock_exec.assert_not_called()  # vcgencmd subprocess must not be spawned when sysfs works


# ── get_throttle_status: vcgencmd fallback ──────────────────────────────────────

async def test_get_throttle_status_falls_back_to_vcgencmd_when_no_sysfs() -> None:
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(b"throttled=0x50005\n", b""))
    proc.returncode = 0
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        with patch("plugins.system.throttle._find_sysfs_path", return_value=None):
            status = await get_throttle_status()
    assert status.available is True
    assert status.source == "vcgencmd"
    assert status.raw_hex == "0x50005"
    assert status.under_voltage is True
    assert status.under_voltage_occurred is True


# ── get_throttle_status: unavailable ────────────────────────────────────────────

async def test_get_throttle_status_unavailable_when_nothing_works() -> None:
    with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=FileNotFoundError)):
        with patch("plugins.system.throttle._find_sysfs_path", return_value=None):
            status = await get_throttle_status()

    assert status.available is False
    assert status.source == "unavailable"
    assert status.raw_hex is None
    assert status.underpowered is False


# ── ThrottleMonitor ─────────────────────────────────────────────────────────────

async def test_monitor_warns_on_transition_to_underpowered() -> None:
    monitor = ThrottleMonitor(enabled=True, interval_seconds=30)
    bad = MagicMock(available=True, underpowered=True, raw_hex="0x1", source="vcgencmd",
                     under_voltage=True, throttled=False, freq_capped=False, soft_temp_limit=False)

    with capture_logs() as logs:
        with patch("plugins.system.throttle.get_throttle_status", AsyncMock(return_value=bad)):
            await monitor.check_once()

    events = [entry["event"] for entry in logs]
    assert "system.underpowered_detected" in events
    warn_entry = next(e for e in logs if e["event"] == "system.underpowered_detected")
    assert warn_entry["log_level"] == "warning"
    assert monitor.last_status is bad


async def test_monitor_only_warns_once_while_still_bad() -> None:
    monitor = ThrottleMonitor(enabled=True, interval_seconds=30)
    bad = MagicMock(available=True, underpowered=True, raw_hex="0x1", source="vcgencmd",
                     under_voltage=True, throttled=False, freq_capped=False, soft_temp_limit=False)

    with patch("plugins.system.throttle.get_throttle_status", AsyncMock(return_value=bad)):
        with capture_logs() as first_logs:
            await monitor.check_once()
        with capture_logs() as second_logs:
            await monitor.check_once()

    assert "system.underpowered_detected" in [e["event"] for e in first_logs]
    assert "system.underpowered_detected" not in [e["event"] for e in second_logs]


async def test_monitor_logs_recovery() -> None:
    monitor = ThrottleMonitor(enabled=True, interval_seconds=30)
    bad = MagicMock(available=True, underpowered=True, raw_hex="0x1", source="vcgencmd",
                     under_voltage=True, throttled=False, freq_capped=False, soft_temp_limit=False)
    good = MagicMock(available=True, underpowered=False, raw_hex="0x0", source="vcgencmd",
                      under_voltage=False, throttled=False, freq_capped=False, soft_temp_limit=False)

    with patch("plugins.system.throttle.get_throttle_status", AsyncMock(return_value=bad)):
        await monitor.check_once()

    with capture_logs() as logs:
        with patch("plugins.system.throttle.get_throttle_status", AsyncMock(return_value=good)):
            await monitor.check_once()

    events = [entry["event"] for entry in logs]
    assert "system.underpowered_cleared" in events


async def test_monitor_start_stop_lifecycle() -> None:
    monitor = ThrottleMonitor(enabled=True, interval_seconds=0.01)
    ok = MagicMock(available=True, underpowered=False, raw_hex="0x0", source="vcgencmd",
                    under_voltage=False, throttled=False, freq_capped=False, soft_temp_limit=False)
    with patch("plugins.system.throttle.get_throttle_status", AsyncMock(return_value=ok)):
        await monitor.start()
        assert monitor._task is not None
        await monitor.stop()
        assert monitor._task is None


async def test_monitor_disabled_does_not_start() -> None:
    monitor = ThrottleMonitor(enabled=False, interval_seconds=30)
    await monitor.start()
    assert monitor._task is None


async def test_monitor_apply_settings_restarts_loop() -> None:
    monitor = ThrottleMonitor(enabled=False, interval_seconds=30)
    ok = MagicMock(available=True, underpowered=False, raw_hex="0x0", source="vcgencmd",
                    under_voltage=False, throttled=False, freq_capped=False, soft_temp_limit=False)
    with patch("plugins.system.throttle.get_throttle_status", AsyncMock(return_value=ok)):
        await monitor.apply_settings(enabled=True, interval_seconds=5)
        assert monitor._task is not None
        await monitor.stop()
