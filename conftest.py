"""Repository-wide pytest setup.

Runs before any astrolol module is imported: the settings singleton resolves the data
directory (profiles, security.json, logs, ...) at import time, so it has to be redirected
here or the tests would read and write the developer's real ~/.astrolol.
"""
import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

_DATA_DIR = Path(tempfile.mkdtemp(prefix="astrolol-test-data-"))
os.environ["ASTROLOL_DATA_DIR"] = str(_DATA_DIR)
# Never the configuration file of an astrolol installed on this machine (/etc/astrolol/astrolol.toml).
os.environ["ASTROLOL_CONFIG"] = str(_DATA_DIR / "no-such-config.toml")
# Tests keep their files in pytest's temporary folders (tmp_path): astrolol may use them.
os.environ["ASTROLOL_STORAGE_ROOTS"] = json.dumps([tempfile.gettempdir(), str(Path.home())])

# INDI drivers keep saved configs, park data and scope configs in $HOME/.indi. The simulators the
# integration tests start get an empty home from here (tests/indi_server.py), never the developer's.
_INDI_HOME = Path(tempfile.mkdtemp(prefix="astrolol-test-indi-home-"))
os.environ["ASTROLOL_TEST_INDI_HOME"] = str(_INDI_HOME)


@pytest.fixture(autouse=True)
def _empty_data_dir():
    """Every test starts with an empty data directory."""
    for child in _DATA_DIR.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    yield


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_DATA_DIR, ignore_errors=True)
    shutil.rmtree(_INDI_HOME, ignore_errors=True)


def pytest_collection_modifyitems(items):
    """Async tests run in the module's event loop, like their fixtures.

    pyproject's asyncio_default_test_loop_scope says the same, but pytest-asyncio before 1.0
    (Debian 13 ships 0.25) ignores that option.
    """
    from pytest_asyncio import is_async_test

    module_loop = pytest.mark.asyncio(loop_scope="module")
    for item in items:
        marker = item.get_closest_marker("asyncio")
        if is_async_test(item) and not (marker and marker.kwargs):
            item.add_marker(module_loop, append=False)
