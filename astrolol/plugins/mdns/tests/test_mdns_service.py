"""Tests for build_service_info and the interface filtering — no network is touched:
MdnsAdvertiser.start()/stop() are the only parts that open sockets.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from astrolol.plugins.mdns import service
from astrolol.plugins.mdns.models import DEFAULT_PORT, MdnsSettings
from astrolol.plugins.mdns.service import SERVICE_TYPE, build_service_info


def _adapters(**interfaces: list[str]):
    return [
        SimpleNamespace(
            name=name,
            ips=[SimpleNamespace(ip=ip, is_IPv4=True) for ip in ips],
        )
        for name, ips in interfaces.items()
    ]


@pytest.fixture
def host(monkeypatch):
    monkeypatch.setattr(service.socket, "gethostname", lambda: "astropi.lan")
    monkeypatch.setattr(service.ifaddr, "get_adapters", lambda: _adapters(eth0=["192.168.1.50"]))


def test_advertises_this_machine_as_hostname_dot_local(host) -> None:
    info = build_service_info(MdnsSettings(advertised_port=8000))
    assert info.server == "astropi.local."
    assert info.type == SERVICE_TYPE
    assert info.parsed_addresses() == ["192.168.1.50"]


def test_port_defaults_to_the_one_astrolol_binds(host) -> None:
    assert build_service_info(MdnsSettings()).port == DEFAULT_PORT
    assert build_service_info(MdnsSettings(advertised_port=443)).port == 443


def test_instance_name_defaults_to_hostname(host) -> None:
    assert build_service_info(MdnsSettings()).name == f"astropi.{SERVICE_TYPE}"


def test_instance_name_override(host) -> None:
    info = build_service_info(MdnsSettings(instance_name="Backyard Rig"))
    assert info.name == f"Backyard Rig.{SERVICE_TYPE}"


def test_properties_carry_version_info(host) -> None:
    props = build_service_info(MdnsSettings(scheme="https")).properties
    assert props[b"scheme"] == b"https"
    assert b"protocol_version" in props
    assert b"server_version" in props


def test_virtual_interfaces_are_not_advertised(monkeypatch) -> None:
    monkeypatch.setattr(service.ifaddr, "get_adapters", lambda: _adapters(
        lo=["127.0.0.1"],
        eth0=["192.168.1.50"],
        wlan0=["10.42.0.1"],
        docker0=["172.17.0.1"],
        **{"br-1a2b3c": ["172.18.0.1"], "tailscale0": ["100.64.0.2"], "veth12": ["172.19.0.1"]},
    ))
    assert service._local_addresses() == ["192.168.1.50", "10.42.0.1"]


def test_link_local_addresses_are_kept(monkeypatch) -> None:
    monkeypatch.setattr(service.ifaddr, "get_adapters", lambda: _adapters(eth0=["169.254.12.7"]))
    assert service._local_addresses() == ["169.254.12.7"]


def test_all_virtual_falls_back_to_them_rather_than_nothing(monkeypatch) -> None:
    monkeypatch.setattr(service.ifaddr, "get_adapters", lambda: _adapters(docker0=["172.17.0.1"]))
    assert service._local_addresses() == ["172.17.0.1"]


def test_no_interface_at_all_falls_back_to_loopback(monkeypatch) -> None:
    monkeypatch.setattr(service.ifaddr, "get_adapters", lambda: _adapters(lo=["127.0.0.1"]))
    assert service._local_addresses() == ["127.0.0.1"]
