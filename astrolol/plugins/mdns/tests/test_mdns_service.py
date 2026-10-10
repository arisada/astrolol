"""Tests for build_service_info — the part with actual branching logic.

Doesn't touch the network: MdnsAdvertiser.start()/stop() (which do) are covered via
test_mdns_api.py's no-port case, which never reaches AsyncZeroconf.
"""
from __future__ import annotations

import socket

from astrolol.plugins.mdns.models import MdnsSettings
from astrolol.plugins.mdns.service import SERVICE_TYPE, build_service_info


def test_no_port_means_nothing_to_advertise() -> None:
    assert build_service_info(MdnsSettings()) is None


def test_default_settings_advertise_local_hostname() -> None:
    info = build_service_info(MdnsSettings(advertised_port=8000))
    assert info is not None
    assert info.port == 8000
    assert info.server == f"{socket.gethostname()}.local."
    assert info.type == SERVICE_TYPE


def test_ip_override_is_used_as_the_address() -> None:
    info = build_service_info(MdnsSettings(advertised_host="192.168.1.50", advertised_port=443))
    assert info is not None
    assert info.parsed_addresses() == ["192.168.1.50"]
    assert info.server == f"{socket.gethostname()}.local."


def test_hostname_override_becomes_the_server_name() -> None:
    info = build_service_info(
        MdnsSettings(advertised_host="astrolol.example.lan", advertised_port=443)
    )
    assert info is not None
    assert info.server == "astrolol.example.lan."


def test_instance_name_defaults_to_hostname() -> None:
    info = build_service_info(MdnsSettings(advertised_port=8000))
    assert info is not None
    assert info.name == f"{socket.gethostname()}.{SERVICE_TYPE}"


def test_instance_name_override() -> None:
    info = build_service_info(
        MdnsSettings(advertised_port=8000, instance_name="Backyard Rig")
    )
    assert info is not None
    assert info.name == f"Backyard Rig.{SERVICE_TYPE}"


def test_properties_carry_version_info() -> None:
    info = build_service_info(MdnsSettings(advertised_port=8000, scheme="https"))
    assert info is not None
    props = info.properties
    assert props[b"scheme"] == b"https"
    assert b"protocol_version" in props
    assert b"server_version" in props
