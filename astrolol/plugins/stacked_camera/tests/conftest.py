"""Fixtures for the stacked camera tests."""
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from astrolol.plugins.stacked_camera import adapters
from astrolol.plugins.stacked_camera.tests.rig import Rig


@pytest.fixture()
async def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Rig]:
    rig = Rig(tmp_path)
    monkeypatch.setattr(adapters, "FRAME_WAIT_EXTRA", 0.5)
    yield rig
    await rig.plugin.shutdown()
