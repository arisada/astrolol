"""Every literal t('key') used in the UI source must exist in the English catalogue.

A missing key silently renders as the raw key, so catch typos here instead of in the browser.
Only literal keys are checked; template-literal keys (t(`kind.${x}`)) are checked by prefix.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

_USE_ALIAS = re.compile(r"const\s*\{\s*t(?::\s*(\w+))?[^}]*\}\s*=\s*useTranslation\((?:'([\w-]+)')?\)")
# `i18n.t(..., { ns })` calls name their namespace explicitly and are not matched here
# Non-React code (the store) defines a local `t` bound to one namespace: i18n.t(key, { ns: 'x', ... })
_LOCAL_T = re.compile(r"const t = \(key: string[^\n]*ns: '([\w-]+)'")
_CALL = re.compile(r"(?<![.\w])(t|tc)\(\s*(['`])([^'`]+)\2")


def _catalogue(ns_dir: Path, ns: str) -> dict:
    return json.loads((ns_dir / f"{ns}.json").read_text())


def _lookup(cat: dict, key: str) -> bool:
    node = cat
    for part in key.split("."):
        if not isinstance(node, dict):
            return False
        if part in node:
            node = node[part]
        elif f"{part}_other" in node or f"{part}_one" in node:
            return True
        else:
            return False
    return True


def _sources() -> list[tuple[Path, Path, str | None]]:
    out = []
    for f in (ROOT / "ui/src").rglob("*.ts*"):
        if "locales" not in f.parts:
            out.append((f, ROOT / "ui/src/locales/en", None))
    for f in ROOT.glob("plugins/*/ui/**/*.ts*"):
        pid = f.relative_to(ROOT / "plugins").parts[0]
        out.append((f, ROOT / f"plugins/{pid}/ui/locales", pid))
    return out


@pytest.mark.parametrize("path,cat_dir,plugin_id", _sources(), ids=lambda p: str(p.relative_to(ROOT)) if isinstance(p, Path) and ROOT in p.parents else None)
def test_keys_exist(path: Path, cat_dir: Path, plugin_id: str | None) -> None:
    text = path.read_text()
    aliases: dict[str, str] = {}  # local function name -> namespace
    for m in _USE_ALIAS.finditer(text):
        name = m.group(1) or "t"
        aliases[name] = m.group(2) or "common"
    for m in _LOCAL_T.finditer(text):
        aliases["t"] = m.group(1)
    if not aliases:
        return

    missing = []
    for m in _CALL.finditer(text):
        fn, quote, key = m.groups()
        if fn not in aliases:
            continue
        ns = aliases[fn]
        if plugin_id is not None and ns == plugin_id:
            cat = json.loads((cat_dir / "en.json").read_text())
        elif plugin_id is not None:
            # a plugin borrowing a core namespace (e.g. `common`) via a second useTranslation()
            cat = _catalogue(ROOT / "ui/src/locales/en", ns)
        else:
            cat = _catalogue(cat_dir, ns)
        if "${" in key:
            prefix = key.split("${")[0].rstrip(".")
            ok = _lookup(cat, prefix) if prefix else True
        else:
            ok = _lookup(cat, key)
        if not ok:
            missing.append(f"{ns}:{key}")
    assert not missing, f"keys missing from the English catalogue: {sorted(set(missing))}"
