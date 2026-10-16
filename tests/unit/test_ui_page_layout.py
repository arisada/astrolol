"""Every page is either a centred column built with <Page>, or a workspace that fills the screen.

A page that sets its own max-width and padding drifts from the others and misbehaves next to the
dock or on a phone, so new pages use <Page width="narrow|medium|wide"> (ui/src/components/Page.tsx).
Workspace pages (a viewer with a sidebar, a log) are listed here on purpose.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

WORKSPACE_PAGES = {
    "ui/src/pages/Imaging.tsx",
    "ui/src/pages/Logs.tsx",
    "astrolol/plugins/autofocus/ui/AutofocusPage.tsx",
    "astrolol/plugins/flat_wizard/ui/FlatWizardPage.tsx",
    "astrolol/plugins/platesolve/ui/PlatesolvePage.tsx",
    "astrolol/plugins/viewer/ui/ViewerPage.tsx",
}

def _pages() -> list[Path]:
    return sorted([*(ROOT / "ui/src/pages").glob("*.tsx"), *ROOT.glob("astrolol/plugins/*/ui/*Page.tsx")])


def test_pages_use_the_page_frame_or_are_listed_workspaces() -> None:
    offenders = []
    for path in _pages():
        rel = path.relative_to(ROOT).as_posix()
        if rel in WORKSPACE_PAGES:
            continue
        if "<Page " not in path.read_text():
            offenders.append(rel)
    assert not offenders, f"use <Page> from '@/components/Page' (or list a workspace page here): {offenders}"


def test_workspace_list_has_no_stale_entries() -> None:
    for rel in WORKSPACE_PAGES:
        assert (ROOT / rel).exists(), f"{rel} no longer exists: remove it from the list"
    assert not [r for r in WORKSPACE_PAGES if "<Page " in (ROOT / r).read_text()], "listed workspace now uses <Page>"
