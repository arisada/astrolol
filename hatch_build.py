"""Put the built web UI (ui/dist) into the wheel as astrolol/_ui, so an installed astrolol serves it.

An editable install (`pip install -e .`) skips it: there static.py finds ui/dist in the checkout.
A wheel built before `npm run build` gets no UI and says so; set ASTROLOL_REQUIRE_UI=1 (the
package builds do) to make that an error instead.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class UiBuildHook(BuildHookInterface):  # type: ignore[type-arg]
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name != "wheel" or version == "editable":
            return
        dist = Path(self.root) / "ui" / "dist"
        if (dist / "index.html").is_file():
            build_data["force_include"][str(dist)] = "astrolol/_ui"
        elif os.environ.get("ASTROLOL_REQUIRE_UI"):
            raise RuntimeError(f"{dist} has no built UI: run `npm run build` in ui/ first")
        else:
            self.app.display_warning(f"{dist} has no built UI: this wheel will not serve the web UI")
