"""Only installed drivers, by plain name, or astrolol's own: what a server may be told to run."""
from __future__ import annotations

from pathlib import Path

import pytest

from astrolol.config.settings import settings
from astrolol.devices.indi import indigo
from astrolol.devices.indi import server as server_mod
from astrolol.devices.indi.allowed import DriverNotAllowed, check_driver
from astrolol.devices.indi.server import IndiServer

CATALOG = ["indi_asi_ccd", "indi_simulator_telescope", "indigo_ccd_asi"]


def _check(executable: str, run_dir: Path) -> None:
    check_driver(executable, run_dir, lambda: CATALOG)


def test_installed_drivers_are_allowed(tmp_path: Path) -> None:
    for name in CATALOG:
        _check(name, tmp_path)


@pytest.mark.parametrize("bad", [
    "/bin/sh", "../bin/sh", "./indi_asi_ccd", "indi_asi_ccd -n x", "indi_asi_ccd\nstart /bin/sh",
    "-v", "", "indi asi", "indi_asi_ccd;id",
])
def test_anything_but_a_plain_name_is_refused(bad: str, tmp_path: Path) -> None:
    with pytest.raises(DriverNotAllowed, match="not a driver name"):
        _check(bad, tmp_path)


def test_a_driver_not_installed_is_refused(tmp_path: Path) -> None:
    with pytest.raises(DriverNotAllowed, match="extra_drivers"):
        _check("indi_not_here", tmp_path)


def test_extra_drivers_from_the_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "extra_drivers", ["indi_my_own"])
    _check("indi_my_own", tmp_path)


def test_astrolols_own_drivers_in_its_run_dir(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _check(str(run_dir / "astrolol-indi-mount-proxy"), run_dir)
    # The same name anywhere else is someone else's program.
    with pytest.raises(DriverNotAllowed):
        _check(str(tmp_path / "astrolol-indi-mount-proxy"), run_dir)
    with pytest.raises(DriverNotAllowed):
        _check(str(run_dir / "sub" / "astrolol-indi-mount-proxy"), run_dir)
    with pytest.raises(DriverNotAllowed):
        _check(str(run_dir / ".." / "astrolol-indi-mount-proxy"), run_dir)


async def test_indiserver_is_never_told_to_run_a_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    written: list[str] = []

    async def fifo_write(_self: IndiServer, line: str) -> None:
        written.append(line)

    monkeypatch.setattr(IndiServer, "_fifo_write", fifo_write)
    monkeypatch.setattr(server_mod, "indi_catalog", lambda: CATALOG)
    server = IndiServer(manage=True, run_dir=tmp_path)
    for bad in ("/bin/sh", "indi_asi_ccd\nstart /bin/sh", "indi_not_here"):
        with pytest.raises(DriverNotAllowed):
            await server.load_driver(bad)
    await server.load_driver("indi_asi_ccd")
    assert written == ["start indi_asi_ccd\n"]


async def test_an_unmanaged_server_loads_nothing_so_checks_nothing(tmp_path: Path) -> None:
    # A remote server runs its own drivers: astrolol sends it nothing.
    await IndiServer(manage=False, run_dir=tmp_path).load_driver("indi_not_here")


class _QuietClient:
    """An INDIGO client whose server lists no drivers."""

    async def wait_for_property(self, *_a: object, **_k: object) -> None:
        return None

    def _get_vector(self, *_a: object) -> None:
        return None


async def test_indigo_is_never_told_to_load_a_path(tmp_path: Path) -> None:
    server = indigo.IndigoServer(
        _QuietClient(), run_dir=tmp_path, server_path=str(tmp_path / "none"),  # type: ignore[arg-type]
    )
    # (Names not starting with indigo_ are refused before: INDI drivers are given at start.)
    for bad in ("indigo_x/../../tmp/evil.so", "indigo_ccd_asi\n", "indigo_not_here"):
        with pytest.raises(DriverNotAllowed):
            await server.load_driver(bad)


def test_indigo_starts_only_allowed_indi_drivers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(indigo, "indi_catalog", lambda: CATALOG)
    server = indigo.IndigoServer(_QuietClient(), run_dir=tmp_path)  # type: ignore[arg-type]
    assert server._allowed_indi("indi_simulator_telescope")
    assert server._allowed_indi(str(tmp_path / "astrolol-indi-mount-proxy"))
    assert not server._allowed_indi("/usr/bin/python3")
