import pytest

from astrolol.plugins.sequencer import guiding


@pytest.fixture(autouse=True)
def fast_guiding_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guiding health is re-checked every second in production; every few ms in tests."""
    monkeypatch.setattr(guiding, "POLL_S", 0.005)
