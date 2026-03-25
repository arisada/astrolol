from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

UI_DIST = Path(__file__).parent.parent.parent / "ui" / "dist"


def mount_ui(app: FastAPI) -> None:
    """
    Serve the built React app from ui/dist/.
    Only called when the dist directory exists (i.e. after `npm run build`).
    In development, the Vite dev server handles the UI.
    """
    if not UI_DIST.exists():
        return

    app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        # API routes are registered before this catch-all, so they take priority.
        # Anything else gets index.html (client-side routing).
        return FileResponse(UI_DIST / "index.html")
