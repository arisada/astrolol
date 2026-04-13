"""Tests for DeviceConfig auto-ID generation and validation."""
import re
import pytest
from pydantic import ValidationError

from astrolol.devices.config import DeviceConfig, _friendly_id, _DEVICE_ID_RE


# ── _friendly_id helper ───────────────────────────────────────────────────────

def test_friendly_id_uses_device_name():
    result = _friendly_id("focuser", {"device_name": "ZWO Focuser", "executable": "indi_asi_focuser"})
    assert result == "focuser_zwo_focuser"


def test_friendly_id_strips_indi_prefix_from_executable():
    result = _friendly_id("mount", {"executable": "indi_eqmod_telescope"})
    assert result == "mount_eqmod_telescope"


def test_friendly_id_camera_from_executable():
    result = _friendly_id("camera", {"executable": "indi_asi_ccd"})
    assert result == "camera_asi_ccd"


def test_friendly_id_slugifies_spaces_and_special_chars():
    result = _friendly_id("camera", {"device_name": "ZWO CCD ASI294MC Pro"})
    assert result == "camera_zwo_ccd_asi294mc_pro"


def test_friendly_id_no_params_uses_random_hex():
    result = _friendly_id("focuser", {})
    assert result.startswith("focuser_")
    # random hex suffix is 8 chars
    suffix = result[len("focuser_"):]
    assert re.fullmatch(r"[0-9a-f]{8}", suffix)


def test_friendly_id_always_valid():
    """Auto-generated IDs must always satisfy the device_id regex."""
    cases = [
        ("camera", {"device_name": "ZWO CCD ASI294MC Pro", "executable": "indi_asi_ccd"}),
        ("mount", {"executable": "indi_eqmod_telescope"}),
        ("focuser", {"device_name": "Pegasus FocusCube 3"}),
        ("camera", {}),
    ]
    for kind, params in cases:
        result = _friendly_id(kind, params)
        assert _DEVICE_ID_RE.match(result), f"Invalid ID generated: {result!r}"


# ── DeviceConfig auto-generation ──────────────────────────────────────────────

def test_blank_device_id_is_auto_generated():
    cfg = DeviceConfig(
        kind="focuser",
        adapter_key="indi_focuser",
        params={"device_name": "ZWO Focuser", "executable": "indi_asi_focuser"},
    )
    assert cfg.device_id == "focuser_zwo_focuser"


def test_missing_device_id_is_auto_generated():
    """If device_id is omitted entirely, a friendly name is generated."""
    cfg = DeviceConfig(
        kind="mount",
        adapter_key="indi_mount",
        params={"executable": "indi_eqmod_telescope"},
    )
    assert cfg.device_id == "mount_eqmod_telescope"


def test_explicit_device_id_is_preserved():
    cfg = DeviceConfig(
        device_id="main_camera",
        kind="camera",
        adapter_key="indi_camera",
    )
    assert cfg.device_id == "main_camera"


# ── DeviceConfig validation ───────────────────────────────────────────────────

@pytest.mark.parametrize("valid_id", [
    "main_camera",
    "mount1",
    "focuser-zwo",
    "a",
    "A1-b_C",
    "a" * 64,          # exactly 64 chars
])
def test_valid_device_ids_accepted(valid_id: str):
    cfg = DeviceConfig(device_id=valid_id, kind="camera", adapter_key="indi_camera")
    assert cfg.device_id == valid_id


@pytest.mark.parametrize("bad_id", [
    "../etc/passwd",      # path traversal
    "/etc/passwd",        # absolute path
    "has space",          # space
    "_leading_underscore",# leading underscore
    "-leading-hyphen",    # leading hyphen
    "a" * 65,             # too long (65 chars)
    "has/slash",          # forward slash
    "has\\backslash",     # backslash
    "semi;colon",         # semicolon
    "tab\there",          # tab
    "new\nline",          # newline
])
def test_invalid_device_ids_rejected(bad_id: str):
    with pytest.raises(ValidationError, match="device_id"):
        DeviceConfig(device_id=bad_id, kind="camera", adapter_key="indi_camera")
