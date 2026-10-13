"""The user guide: every relative link resolves, and every plugin page has a guide page.

The guide is read on GitHub and inside the app (ui/src/help/), both following the same
relative links, so a broken link is broken in both places.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGINS = ROOT / "astrolol" / "plugins"
PAGES = sorted([*(ROOT / "docs").rglob("*.md"), *PLUGINS.glob("*/docs/*.md")])
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.*)$", re.MULTILINE)
CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)


def github_slug(heading: str) -> str:
    """The anchor GitHub (and rehype-slug in the app) gives a heading."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def anchors(page: Path) -> set[str]:
    text = CODE_BLOCK.sub("", page.read_text())
    return {github_slug(h) for h in HEADING.findall(text)}


@pytest.mark.parametrize("page", PAGES, ids=lambda p: str(p.relative_to(ROOT)))
def test_relative_links_resolve(page: Path) -> None:
    text = CODE_BLOCK.sub("", page.read_text())
    broken = []
    for href in LINK.findall(text):
        if re.match(r"[a-z][a-z0-9+.-]*:", href, re.IGNORECASE):
            continue
        path, _, anchor = href.partition("#")
        target = (page.parent / path).resolve() if path else page
        if not target.exists():
            broken.append(f"{href}: no such file")
        elif anchor and target.suffix == ".md" and anchor not in anchors(target):
            broken.append(f"{href}: no heading #{anchor}")
    assert not broken, broken


def test_every_plugin_page_has_a_guide_page() -> None:
    """The help button on a plugin's page opens astrolol/plugins/<id>/docs/en.md."""
    with_ui = {p.parent.parent.name for p in PLUGINS.glob("*/ui/index.ts")}
    missing = sorted(pid for pid in with_ui - {"hello"} if not (PLUGINS / pid / "docs" / "en.md").exists())
    assert not missing, f"plugins with a page but no docs/en.md: {missing}"
