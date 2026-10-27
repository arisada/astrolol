"""Which drivers astrolol lets an INDI or INDIGO server run.

A driver's name comes from the user (Load driver, a profile's device), and the server runs
whatever it is given, a full path included. So it must be a plain name, in the INDI or INDIGO
driver catalog installed on this machine (or in `extra_drivers` of the start-up configuration),
or one of astrolol's own drivers in its run directory.
"""
from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from pathlib import Path

from astrolol.config.settings import CONFIG_FILE, settings

# No path, no option, no white space: the name ends up on a command line or in a command pipe.
_PLAIN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}")


class DriverNotAllowed(ValueError):
    pass


def is_own_driver(executable: str, run_dir: Path) -> bool:
    """One of astrolol's own drivers (the INDI mount proxy), which it writes in *run_dir*."""
    path = Path(executable)
    return (
        path.is_absolute()
        and _PLAIN_NAME.fullmatch(path.name) is not None
        and os.path.realpath(path.parent) == os.path.realpath(run_dir)
    )


def check_driver(executable: str, run_dir: Path, catalog: Callable[[], Iterable[str]]) -> None:
    """Raise DriverNotAllowed unless the server may run *executable*.

    *catalog* lists the drivers installed on this machine; it is only read for a plain name.
    """
    if is_own_driver(executable, run_dir):
        return
    if _PLAIN_NAME.fullmatch(executable) is None:
        raise DriverNotAllowed(f"{executable!r} is not a driver name")
    if executable in settings.extra_drivers or executable in set(catalog()):
        return
    raise DriverNotAllowed(
        f"{executable} is not an installed driver; add it to extra_drivers in {CONFIG_FILE} "
        "if it is one"
    )


def indi_catalog() -> list[str]:
    from astrolol.devices.indi.catalog import load_catalog

    return [e.executable for e in load_catalog()]
