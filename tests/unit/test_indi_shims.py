"""astrolol's own INDI shims: startup-driver hook and shielding from device listings."""
import pytest

from astrolol.devices.indi.client import IndiClient, is_astrolol_shim
from astrolol.devices.indi.plugin import IndiConnectionManager


class _FakeServer:
    def __init__(self) -> None:
        self.started = 0
        self.loaded: list[str] = []
        self.unloaded: list[str] = []

    async def start(self) -> None:
        self.started += 1

    async def load_driver(self, executable: str) -> None:
        self.loaded.append(executable)

    async def unload_driver(self, executable: str) -> None:
        self.unloaded.append(executable)


class _FakeClient:
    async def connect(self) -> None:
        pass


def _manager(tmp_path) -> tuple[IndiConnectionManager, _FakeServer]:
    manager = IndiConnectionManager(run_dir=tmp_path)
    server = _FakeServer()
    manager._server = server  # type: ignore[assignment]
    manager._client = _FakeClient()  # type: ignore[assignment]
    return manager, server


@pytest.mark.asyncio
async def test_startup_driver_is_loaded_when_indiserver_starts(tmp_path) -> None:
    manager, server = _manager(tmp_path)
    await manager.add_startup_driver("/run/astrolol-indi-mount-proxy")
    assert server.loaded == []  # indiserver not started yet: just remembered
    await manager.acquire()
    assert server.loaded == ["/run/astrolol-indi-mount-proxy"]


@pytest.mark.asyncio
async def test_startup_driver_added_while_running_loads_immediately(tmp_path) -> None:
    manager, server = _manager(tmp_path)
    await manager.ensure_started()
    await manager.add_startup_driver("proxy")
    assert server.loaded == ["proxy"]


@pytest.mark.asyncio
async def test_removing_a_startup_driver_unloads_it(tmp_path) -> None:
    manager, server = _manager(tmp_path)
    await manager.add_startup_driver("proxy")
    await manager.ensure_started()
    await manager.remove_startup_driver("proxy")
    assert server.unloaded == ["proxy"]
    assert manager._startup_drivers == []


@pytest.mark.asyncio
async def test_a_failing_startup_driver_does_not_break_indi(tmp_path) -> None:
    manager, server = _manager(tmp_path)

    async def boom(executable: str) -> None:
        raise OSError("fifo gone")

    server.load_driver = boom  # type: ignore[method-assign]
    await manager.add_startup_driver("proxy")
    await manager.acquire()  # must not raise


def test_is_astrolol_shim() -> None:
    assert is_astrolol_shim("astrolol Mount Proxy")
    assert not is_astrolol_shim("EQMod Mount")
    assert not is_astrolol_shim("astrololX")


def test_shims_are_hidden_from_device_listings() -> None:
    client = IndiClient()
    client.data["ZWO CCD ASI120MM"] = {}
    client.data["astrolol Mount Proxy"] = {}
    assert client.list_devices() == ["ZWO CCD ASI120MM"]
