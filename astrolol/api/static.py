import os
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logger = structlog.get_logger()

# Candidate locations for ui/dist, in priority order:
#   1. ASTROLOL_UI_DIST env var (explicit override)
#   2. Relative to this source file (works with `pip install -e .` from a git clone)
#   3. Current working directory (works when running `python -m astrolol.main` from the repo root)
def _find_ui_dist() -> Path | None:
    if env := os.environ.get("ASTROLOL_UI_DIST"):
        p = Path(env)
        if p.is_dir():
            return p
        logger.warning("static.ui_dist_env_not_found", path=str(p))
        return None

    candidates = [
        Path(__file__).parent.parent.parent / "ui" / "dist",  # editable install / source tree
        Path.cwd() / "ui" / "dist",                           # cwd fallback (e.g. cd /repo && python -m astrolol.main)
    ]
    for p in candidates:
        if p.is_dir() and (p / "index.html").exists():
            return p
    return None


UI_DIST: Path | None = _find_ui_dist()


def mount_ui(app: FastAPI) -> None:
    """
    Serve the built React app from ui/dist/.
    Only called when the dist directory exists (i.e. after `npm run build`).
    In development, the Vite dev server handles the UI.
    """
    if UI_DIST is None:
        logger.warning(
            "static.ui_not_found",
            message=(
                "ui/dist not found — UI will not be served. "
                "Run `npm run build` inside the ui/ directory, or set the "
                "ASTROLOL_UI_DIST environment variable to the dist path."
            ),
        )
        return

    logger.info("static.ui_mounted", path=str(UI_DIST))
    app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        # API routes are registered before this catch-all, so they take priority.
        # Anything else (including root /) gets index.html (client-side routing).
        return FileResponse(UI_DIST / "index.html")
