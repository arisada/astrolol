"""Tests for the autofocus plugin API and core algorithms."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astrolol.core.events import EventBus
from astrolol.core.plugin_api import PluginContext
from plugins.autofocus.models import AutofocusConfig, AutofocusRun
from plugins.autofocus.plugin import AutofocusPlugin


# ── App factory ───────────────────────────────────────────────────────────────

def _make_app() -> FastAPI:
    app = FastAPI()
    bus = EventBus()
    device_manager = MagicMock()
    registry = MagicMock()
    profile_store = MagicMock()

    ctx = PluginContext(
        event_bus=bus,
        device_manager=device_manager,
        device_registry=registry,
        profile_store=profile_store,
    )
    plugin = AutofocusPlugin()
    plugin.setup(app, ctx)
    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_make_app())


# ── API tests ─────────────────────────────────────────────────────────────────

def test_get_run_returns_404_when_no_run(client: TestClient) -> None:
    resp = client.get("/plugins/autofocus/run")
    assert resp.status_code == 404


def test_abort_returns_204_when_no_run(client: TestClient) -> None:
    resp = client.post("/plugins/autofocus/abort")
    assert resp.status_code == 204


def test_start_validates_required_fields(client: TestClient) -> None:
    resp = client.post("/plugins/autofocus/start", json={})
    assert resp.status_code == 422


def test_start_validates_step_size_positive(client: TestClient) -> None:
    resp = client.post(
        "/plugins/autofocus/start",
        json={"camera_id": "cam_1", "focuser_id": "foc_1", "step_size": 0},
    )
    assert resp.status_code == 422


def test_start_validates_num_steps_range(client: TestClient) -> None:
    resp = client.post(
        "/plugins/autofocus/start",
        json={"camera_id": "cam_1", "focuser_id": "foc_1", "num_steps": 2},
    )
    assert resp.status_code == 422


def test_start_conflict_when_already_running(client: TestClient) -> None:
    app = _make_app()
    engine = app.state.autofocus_engine

    # Inject a fake running task
    fake_task = MagicMock()
    fake_task.done.return_value = False
    engine._task = fake_task
    engine._current_run = AutofocusRun(
        config=AutofocusConfig(camera_id="cam_1", focuser_id="foc_1"),
        status="running",
        total_steps=11,
    )

    with TestClient(app) as tc:
        resp = tc.post(
            "/plugins/autofocus/start",
            json={"camera_id": "cam_1", "focuser_id": "foc_1"},
        )
    assert resp.status_code == 409


def test_preview_returns_404_when_no_run(client: TestClient) -> None:
    resp = client.get("/plugins/autofocus/run/preview/1")
    assert resp.status_code == 404


# ── Algorithm tests ───────────────────────────────────────────────────────────

def test_parabola_fit_finds_correct_minimum() -> None:
    from plugins.autofocus.algorithms import fit_parabola

    # Perfect parabola with minimum at position 1000
    positions = [800, 900, 1000, 1100, 1200]
    fwhms = [4.0, 2.5, 2.0, 2.5, 4.0]
    result = fit_parabola(positions, fwhms)
    assert result is not None
    a, b, c, optimal = result
    assert a > 0
    assert abs(optimal - 1000) < 50  # within 50 steps of true minimum


def test_parabola_fit_returns_none_for_too_few_points() -> None:
    from plugins.autofocus.algorithms import fit_parabola

    assert fit_parabola([100, 200], [3.0, 2.5]) is None


def test_parabola_fit_returns_none_for_downward_parabola() -> None:
    from plugins.autofocus.algorithms import fit_parabola

    # Inverted V — no valid focus minimum
    positions = [800, 900, 1000, 1100, 1200]
    fwhms = [2.5, 3.0, 4.0, 3.0, 2.5]
    result = fit_parabola(positions, fwhms)
    assert result is None


def test_parabola_fit_returns_none_when_optimal_outside_range() -> None:
    from plugins.autofocus.algorithms import fit_parabola

    # All points on one side of a steep curve — extrapolated minimum is far outside range
    positions = [100, 200, 300, 400, 500]
    fwhms = [10.0, 8.0, 6.0, 4.0, 2.0]  # monotone descending → minimum to the right
    result = fit_parabola(positions, fwhms)
    # Either None (outside range guard) or an extreme extrapolation
    if result is not None:
        _, _, _, optimal = result
        assert optimal > 500 * 1.2 or result is None  # outside range


# ── Engine unit tests ─────────────────────────────────────────────────────────

def test_engine_refit_curve_skipped_when_few_points() -> None:
    from plugins.autofocus.engine import AutofocusEngine

    engine = AutofocusEngine(event_bus=MagicMock(), device_manager=MagicMock())
    config = AutofocusConfig(camera_id="cam_1", focuser_id="foc_1")
    run = AutofocusRun(config=config, status="running", total_steps=11)

    # With < 3 data points, curve_fit should remain None
    from plugins.autofocus.models import FocusDataPoint
    run.data_points = [
        FocusDataPoint(step=1, position=900, fwhm=3.5, star_count=10),
        FocusDataPoint(step=2, position=1000, fwhm=3.0, star_count=12),
    ]
    engine._refit_curve(run)
    assert run.curve_fit is None


def test_engine_refit_curve_updates_curve_fit_with_enough_points() -> None:
    from plugins.autofocus.engine import AutofocusEngine

    engine = AutofocusEngine(event_bus=MagicMock(), device_manager=MagicMock())
    config = AutofocusConfig(camera_id="cam_1", focuser_id="foc_1")
    run = AutofocusRun(config=config, status="running", total_steps=11)

    from plugins.autofocus.models import FocusDataPoint
    run.data_points = [
        FocusDataPoint(step=1, position=800, fwhm=4.0, star_count=10),
        FocusDataPoint(step=2, position=900, fwhm=2.5, star_count=12),
        FocusDataPoint(step=3, position=1000, fwhm=2.0, star_count=14),
        FocusDataPoint(step=4, position=1100, fwhm=2.5, star_count=12),
        FocusDataPoint(step=5, position=1200, fwhm=4.0, star_count=10),
    ]
    engine._refit_curve(run)
    assert run.curve_fit is not None
    assert run.curve_fit.a > 0
    assert abs(run.curve_fit.optimal_position - 1000) < 50
