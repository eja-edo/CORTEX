"""Serves the built console (`web/dist`) at /app so the whole product is one service on one origin: the session cookie
and the CSRF header need no CORS. Anything under /app that is not a real file is the SPA's own route (client-side
routing), so a reload on /app/inbox/<id> works. The page is never cached; hashed assets are cached for a year."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

DEFAULT_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self' https://www.googleapis.com; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


def mount_spa(app: FastAPI, dist: Path | None = None) -> bool:
    """False (and nothing mounted) when there is no build: the API still works without the UI."""
    dist = dist or DEFAULT_DIST
    index = dist / "index.html"
    if not index.is_file():
        return False
    app.mount("/app/assets", StaticFiles(directory=dist / "assets", check_dir=False), name="console-assets")

    @app.get("/app", include_in_schema=False)
    async def bare() -> RedirectResponse:
        return RedirectResponse("/app/")

    @app.get("/app/{path:path}", include_in_schema=False)
    async def spa(path: str) -> Response:
        target = (dist / path).resolve()
        if path and target.is_file() and dist.resolve() in target.parents:  # a real file (favicon…), never outside dist
            return FileResponse(target)
        if path.startswith("assets/") or "." in path.rsplit("/", 1)[-1]:  # a missing file is a 404, not the app
            raise HTTPException(404, "not found")
        return FileResponse(index, headers={"Cache-Control": "no-store", "Content-Security-Policy": CSP,
                                            "X-Frame-Options": "DENY", "X-Content-Type-Options": "nosniff"})

    return True
