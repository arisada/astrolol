import os
from pathlib import Path

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logger = structlog.get_logger()

# Path prefixes that belong to the backend API (mirrors the dev-server proxy
# list in ui/vite.config.ts). No client-side route ever starts with one of
# these, except the pages listed in _CLIENT_ROUTES_SHADOWING_API below — plugin UI
# pages are mounted at "/<plugin_id>", never "/plugins/...".
# A request under one of these that no route matched (e.g. a disabled
# plugin's "/plugins/<id>/..." routes) is a real 404, not a client page.
_API_PREFIXES = frozenset({
    "api", "devices", "profiles", "imager", "mount", "focuser", "filter_wheel", "flat_panel",
    "indi", "inventory", "settings", "events", "health", "plugins", "admin", "ws", "auth",
})

# Client-side pages whose path is also a REST endpoint ("/profiles" lists profiles,
# "/mount/..." drives the mount). The API route wins the match, so a browser reload on
# such a page used to show the JSON. A browser *navigation* to one of these gets the app
# shell instead; fetch() calls from the UI are not navigations and still reach the API.
# tests/unit/test_static_spa.py checks this covers every route declared in ui/src/App.tsx.
_CLIENT_ROUTES_SHADOWING_API = frozenset({"profiles", "mount"})


def _is_page_navigation(request: Request) -> bool:
    """True for a user typing/reloading a URL, never for a script's fetch()/XHR."""
    if request.method not in ("GET", "HEAD"):
        return False
    dest = request.headers.get("sec-fetch-dest")
    if dest is not None:
        return dest == "document"
    # Browsers too old to send Fetch Metadata: a navigation asks for HTML first.
    return request.headers.get("accept", "").startswith("text/html")


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

    @app.middleware("http")
    async def page_navigation(request: Request, call_next):
        first, _, rest = request.url.path.strip("/").partition("/")
        if first in _CLIENT_ROUTES_SHADOWING_API and not rest and _is_page_navigation(request):
            return FileResponse(UI_DIST / "index.html")
        return await call_next(request)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        # API routes are registered before this catch-all, so they take priority.
        # If nothing matched and the path is still under a known API prefix
        # (e.g. a disabled plugin's routes), it's a genuine 404 — don't mask it
        # as a 200 with the SPA shell, or callers can't tell "not found" from
        # "here's your page" (fetch().ok would be true for HTML, not JSON).
        if full_path.split("/", 1)[0] in _API_PREFIXES:
            raise HTTPException(status_code=404, detail="Not Found")
        # vite copies ui/public/* (favicon.ico, manifest.webmanifest, sw.js,
        # icons, ...) into ui/dist/ root at build time. Serve those directly
        # instead of masking them with the SPA shell.
        if full_path:
            candidate = (UI_DIST / full_path).resolve()
            if candidate.is_file() and UI_DIST.resolve() in candidate.parents:
                return FileResponse(candidate)
        # Anything else (including root /) gets index.html (client-side routing).
        return FileResponse(UI_DIST / "index.html")


def reorder_spa_fallback_last(app: FastAPI) -> None:
    """Keep the SPA catch-all last in ``app.router.routes``.

    Starlette matches routes in list order and stops at the first full match
    (see ``starlette.routing.Router.app``), so the catch-all registered by
    ``mount_ui()`` only "loses" to API routes because it was added after all
    of them at startup. Hot-enabling a plugin later (``sync_enabled_plugins``)
    appends its router to the route list at *runtime* — after the catch-all —
    so without this, every request under that plugin's new "/plugins/<id>/..."
    prefix would be swallowed by the catch-all before ever reaching the
    plugin's own routes. Call this right after any such runtime
    ``include_router``/``plugin.setup()`` so the catch-all keeps behaving as
    if it were always registered last. No-op if the UI isn't mounted.

    ``sync_enabled_plugins`` (``astrolol/app.py``) is the only runtime route
    registration path today — if another one is ever added (e.g. a future
    admin endpoint calling ``app.include_router``/``app.mount`` directly), it
    needs this same call too, or it silently reintroduces this bug.
    """
    routes = app.router.routes
    for i, route in enumerate(routes):
        if getattr(route, "name", None) == "spa_fallback":
            routes.append(routes.pop(i))
            return
