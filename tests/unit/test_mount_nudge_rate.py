import pytest
from pydantic import ValidationError

from astrolol.config.user_settings import MountDeviceSettings


def test_nudge_rate_defaults_to_16x():
    assert MountDeviceSettings().nudge_rate == "16x"


@pytest.mark.parametrize("rate", ["1x", "800x", "SLEW_CENTERING", "0.5x"])
def test_nudge_rate_accepts_speeds_and_driver_names(rate):
    assert MountDeviceSettings(nudge_rate=rate).nudge_rate == rate


@pytest.mark.parametrize("bad", ["", "16 x", "a" * 33, "../x"])
def test_nudge_rate_rejects_odd_values(bad):
    with pytest.raises(ValidationError):
        MountDeviceSettings(nudge_rate=bad)


def test_legacy_mount_settings_without_nudge_rate():
    assert MountDeviceSettings.model_validate({"auto_park_enabled": True}).nudge_rate == "16x"
