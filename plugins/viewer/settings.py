"""Persisted viewer settings + the default library_dir heuristic."""
from __future__ import annotations

from pathlib import Path


def default_library_dir(save_dir_template: str) -> Path:
    """The static (non-templated) prefix of *save_dir_template*.

    E.g. "~/astrolol_pictures/%D" -> "~/astrolol_pictures". Falls back to
    "~/astrolol_pictures" outright when the prefix is empty (a template starting with a
    token, e.g. "%D/…") — an empty prefix must never turn into scanning the working
    directory or the filesystem root.
    """
    idx = save_dir_template.find("%")
    prefix = save_dir_template[:idx] if idx >= 0 else save_dir_template
    prefix = prefix.rstrip("/")
    if not prefix:
        prefix = "~/astrolol_pictures"
    return Path(prefix).expanduser()
