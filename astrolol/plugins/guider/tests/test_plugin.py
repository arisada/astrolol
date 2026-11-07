import pytest
from fastapi import FastAPI

from astrolol.core.events import EventBus
from astrolol.core.plugin_api import PluginContext
from astrolol.plugins.guider.guider import BuiltinGuider
from astrolol.plugins.guider.plugin import get_plugin


def ctx() -> PluginContext:
    return PluginContext(event_bus=EventBus(), device_manager=object(), device_registry=object())


async def test_setup_registers_the_guider_and_routes() -> None:
    app, plugin = FastAPI(), get_plugin()
    plugin.setup(app, ctx())
    assert isinstance(app.state.guider, BuiltinGuider) and app.state.guider is app.state.builtin_guider
    assert "/plugins/guider/status" in app.openapi()["paths"]
    await plugin.shutdown()
    assert app.state.guider is None


async def test_guiding_without_a_camera_chosen_fails_clearly() -> None:
    from astrolol.core.guiding import GuiderNotConnected, SettleParams

    app, plugin = FastAPI(), get_plugin()
    plugin.setup(app, ctx())
    with pytest.raises(GuiderNotConnected, match="Choose the guide camera"):
        await app.state.guider.guide(SettleParams())
    await plugin.shutdown()


async def test_a_second_guiding_plugin_does_not_break_setup() -> None:
    """Both can be enabled; PHD2 stays the best real guider only until the built-in one is there."""
    from astrolol.core.guiding import active_guider_id, guiders

    app = FastAPI()
    get_plugin().setup(app, ctx())
    get_plugin().setup(app, ctx())          # the same plugin again just replaces its entry
    assert active_guider_id(app) == "guider" and list(guiders(app)) == ["guider"]
