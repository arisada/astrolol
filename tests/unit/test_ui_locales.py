"""Every translated UI catalogue must have exactly the keys of its English source."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _flatten(d: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, f"{key}."))
        else:
            out[key] = v
    return out


def _placeholders(text: str) -> set[str]:
    return set(re.findall(r"\{\{\s*\w+\s*\}\}|</?\w+>", text))


def _pairs() -> list[tuple[Path, Path]]:
    pairs = []
    for en in ROOT.glob("astrolol/plugins/*/ui/locales/en.json"):
        pairs += [(en, o) for o in en.parent.glob("*.json") if o != en]
    for en in ROOT.glob("ui/src/locales/en/*.json"):
        pairs += [(en, o) for o in en.parent.parent.glob(f"*/{en.name}") if o != en]
    return pairs


@pytest.mark.parametrize("en,other", _pairs(), ids=lambda p: str(p.relative_to(ROOT)))
def test_catalogue_matches_english(en: Path, other: Path) -> None:
    src = _flatten(json.loads(en.read_text()))
    tr = _flatten(json.loads(other.read_text()))
    assert set(tr) == set(src), "missing/extra keys"
    for key, text in src.items():
        assert _placeholders(tr[key]) == _placeholders(text), f"placeholder/tag mismatch in {key}"
