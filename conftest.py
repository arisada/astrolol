"""Repository-wide pytest setup.

Runs before any astrolol module is imported: the settings singleton resolves the data
directory (profiles, security.json, logs, ...) at import time, so it has to be redirected
here or the tests would read and write the developer's real ~/.astrolol.
"""
import os
import shutil
import tempfile
from pathlib import Path

import pytest

_DATA_DIR = Path(tempfile.mkdtemp(prefix="astrolol-test-data-"))
os.environ["ASTROLOL_DATA_DIR"] = str(_DATA_DIR)


@pytest.fixture(autouse=True)
def _empty_data_dir():
    """Every test starts with an empty data directory."""
    for child in _DATA_DIR.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    yield


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_DATA_DIR, ignore_errors=True)
