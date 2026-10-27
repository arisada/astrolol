"""Tests for the automatic Wi-Fi / hotspot watchdog and the nmcli parsing it relies on."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from astrolol.plugins.system import network as net
from astrolol.plugins.system.autonetwork import NetworkWatchdog
from astrolol.plugins.system.models import NetworkMode, NetworkPolicy, NetworkStatus, SystemSettings


def _status(mode: NetworkMode, *, nmcli: bool = True, interface: str | None = "wlan0") -> NetworkStatus:
    return NetworkStatus(
        mode=mode, interface=interface, ssid=None, ip_address=None, gateway=None,
        hotspot_ssid=None, hotspot_ip=None, nmcli_available=nmcli,
    )


class Rig:
    """A watchdog with a controllable clock, uptime, network state and ethernet."""

    def __init__(self, **settings: object) -> None:
        self.settings = SystemSettings(**settings)
        self.mode = NetworkMode.disconnected
        self.ethernet = False
        self.now = 1000.0
        self.uptime = 10_000.0  # long after boot unless a test says otherwise
        self.start = AsyncMock()
        self.dog = NetworkWatchdog(
            lambda: self.settings,
            status_fn=self._status,
            ethernet_fn=self._eth,
            start_hotspot_fn=self.start,
            clock=lambda: self.now,
            uptime_fn=lambda: self.uptime,
        )

    async def _status(self) -> NetworkStatus:
        return _status(self.mode)

    async def _eth(self) -> bool:
        return self.ethernet

    async def tick(self, advance: float = 0.0) -> None:
        self.now += advance
        self.uptime += advance
        await self.dog.tick()


async def test_auto_starts_hotspot_when_nothing_after_boot_window() -> None:
    rig = Rig(boot_wifi_window_seconds=60)
    rig.uptime = 30
    await rig.tick()
    rig.start.assert_not_called()  # still inside the boot window: home Wi-Fi gets its chance
    await rig.tick(40)
    rig.start.assert_awaited_once()
    assert rig.start.await_args.kwargs["ssid"] == "AstroLOL"


async def test_auto_stays_on_wifi_when_connected() -> None:
    rig = Rig()
    rig.mode = NetworkMode.wifi
    await rig.tick()
    await rig.tick(500)
    rig.start.assert_not_called()


async def test_ethernet_counts_as_connected() -> None:
    rig = Rig()
    rig.ethernet = True
    await rig.tick()
    rig.start.assert_not_called()


async def test_lost_wifi_waits_for_grace_period() -> None:
    rig = Rig(lost_wifi_grace_seconds=120)
    rig.mode = NetworkMode.wifi
    await rig.tick()
    rig.mode = NetworkMode.disconnected
    await rig.tick(10)
    await rig.tick(100)
    rig.start.assert_not_called()
    await rig.tick(30)
    rig.start.assert_awaited_once()


async def test_wifi_back_within_grace_cancels_fallback() -> None:
    rig = Rig(lost_wifi_grace_seconds=120)
    rig.mode = NetworkMode.wifi
    await rig.tick()
    rig.mode = NetworkMode.disconnected
    await rig.tick(100)
    rig.mode = NetworkMode.wifi
    await rig.tick(5)
    rig.mode = NetworkMode.disconnected
    await rig.tick(100)  # the clock restarted when the connection came back
    rig.start.assert_not_called()


async def test_wifi_policy_never_starts() -> None:
    rig = Rig(network_policy=NetworkPolicy.wifi)
    await rig.tick(1000)
    rig.start.assert_not_called()


async def test_hotspot_policy_starts_even_with_wifi_but_after_window() -> None:
    rig = Rig(network_policy=NetworkPolicy.hotspot, boot_wifi_window_seconds=60)
    rig.mode = NetworkMode.wifi
    rig.uptime = 10
    await rig.tick()
    rig.start.assert_not_called()
    await rig.tick(60)
    rig.start.assert_awaited_once()


async def test_nothing_done_while_hotspot_is_up() -> None:
    rig = Rig()
    rig.mode = NetworkMode.hotspot
    await rig.tick(1000)
    rig.start.assert_not_called()


async def test_manual_stop_is_respected_until_policy_changes() -> None:
    rig = Rig()
    await rig.tick()  # first look at the policy
    rig.start.reset_mock()
    rig.dog.suppress()
    await rig.tick(100)
    rig.start.assert_not_called()
    rig.settings = rig.settings.model_copy(update={"network_policy": NetworkPolicy.hotspot})
    await rig.tick()
    rig.start.assert_awaited_once()


async def test_manual_stop_cleared_by_a_connection_in_auto() -> None:
    rig = Rig()
    rig.dog.suppress()
    rig.mode = NetworkMode.wifi
    await rig.tick()
    rig.mode = NetworkMode.disconnected
    await rig.tick(1)
    await rig.tick(200)
    rig.start.assert_awaited_once()


async def test_failed_start_is_retried_later() -> None:
    rig = Rig()
    rig.start.side_effect = RuntimeError("busy")
    await rig.tick()
    await rig.tick(10)
    assert rig.start.await_count == 1
    await rig.tick(30)
    assert rig.start.await_count == 2


async def test_no_nmcli_or_no_interface_does_nothing() -> None:
    rig = Rig()

    async def no_nmcli() -> NetworkStatus:
        return _status(NetworkMode.unknown, nmcli=False, interface=None)

    rig.dog._status = no_nmcli
    await rig.tick(1000)
    rig.start.assert_not_called()


# ── nmcli parsing ──────────────────────────────────────────────────────────────

def test_split_terse_handles_escaped_colons() -> None:
    assert net.split_terse(r"My\:Net:802-11-wireless:wlan0") == ["My:Net", "802-11-wireless", "wlan0"]


async def test_status_detects_hotspot_from_profile_mode() -> None:
    answers = {
        ("nmcli", "-t", "-f", "DEVICE,TYPE", "device", "status"): (0, "wlan0:wifi", ""),
        ("nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active"):
            (0, "Field:802-11-wireless:wlan0", ""),
        ("nmcli", "-t", "-f", "802-11-wireless.mode,802-11-wireless.ssid", "connection", "show", "Field"):
            (0, "802-11-wireless.mode:ap\n802-11-wireless.ssid:AstroLOL", ""),
        ("nmcli", "-t", "-f", "IP4.ADDRESS,IP4.GATEWAY", "device", "show", "wlan0"):
            (0, "IP4.ADDRESS[1]:10.42.0.1/24\nIP4.GATEWAY:", ""),
    }

    async def fake_run(*args: str) -> tuple[int, str, str]:
        return answers[args]

    with patch.object(net, "_run", fake_run), patch.object(net, "nmcli_available", lambda: True):
        st = await net.get_network_status()
    assert st.mode == NetworkMode.hotspot
    assert st.hotspot_ssid == "AstroLOL"
    assert st.hotspot_ip == "10.42.0.1"


async def test_ethernet_connected_parses_device_status() -> None:
    async def fake_run(*args: str) -> tuple[int, str, str]:
        return 0, "wifi:disconnected\nethernet:connected\nloopback:unmanaged", ""

    with patch.object(net, "_run", fake_run), patch.object(net, "nmcli_available", lambda: True):
        assert await net.ethernet_connected() is True


async def test_hotspot_is_created_with_wpa2_and_fixed_address() -> None:
    calls: list[tuple[str, ...]] = []

    async def fake_run(*args: str) -> tuple[int, str, str]:
        calls.append(args)
        return 0, "", ""

    with patch.object(net, "_run", fake_run), patch.object(net, "nmcli_available", lambda: True):
        await net.start_hotspot("Sky", "password123", "wlan0")
    add = next(c for c in calls if "add" in c)
    for want in ("rsn", "ccmp", "10.42.0.1/24", "shared"):
        assert want in add
