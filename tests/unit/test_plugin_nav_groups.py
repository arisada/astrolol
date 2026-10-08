"""Every bundled plugin declares which navigation category it belongs to."""
import importlib
import pkgutil

import plugins
from astrolol.core.plugin_api import NavGroup

EXPECTED = {
    "equipment": {"eqmod", "bluetooth_serial", "guide_simulator", "lx200", "stellarium"},
    "settings": {"system", "mdns", "hello"},
}


def _manifests():
    for mod in pkgutil.iter_modules(plugins.__path__):
        if mod.ispkg:
            yield importlib.import_module(f"plugins.{mod.name}.plugin").get_plugin().manifest


def test_groups_are_valid_and_classified():
    valid = set(NavGroup.__args__)
    by_id = {m.id: m.nav_group for m in _manifests()}
    assert set(by_id.values()) <= valid
    for group, ids in EXPECTED.items():
        for pid in ids:
            assert by_id[pid] == group, pid
    # Everything else is an observing feature.
    others = set(by_id) - EXPECTED["equipment"] - EXPECTED["settings"]
    assert all(by_id[p] == "astronomy" for p in others)
