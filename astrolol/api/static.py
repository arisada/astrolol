import os
from pathlib import Path

import structlog
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logger = structlog.get_logger()

# Path prefixes that belong to the backend API (mirrors the dev-server proxy
# list in ui/vite.config.ts). No client-side route ever starts with one of
# these — plugin UI pages are mounted at "/<plugin_id>", never "/plugins/...".
# A request under one of these that no route matched (e.g. a disabled
# plugin's "/plugins/<id>/..." routes) is a real 404, not a client page.
_API_PREFIXES = frozenset({
    "api", "devices", "profiles", "imager", "mount", "focuser", "filter_wheel",
    "indi", "inventory", "settings", "events", "health", "plugins", "admin", "ws",
})

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
        # If nothing matched and the path is still under a known API prefix
        # (e.g. a disabled plugin's routes), it's a genuine 404 — don't mask it
        # as a 200 with the SPA shell, or callers can't tell "not found" from
        # "here's your page" (fetch().ok would be true for HTML, not JSON).
        if full_path.split("/", 1)[0] in _API_PREFIXES:
            raise HTTPException(status_code=404, detail="Not Found")
        # Anything else (including root /) gets index.html (client-side routing).
        return FileResponse(UI_DIST / "index.html")
