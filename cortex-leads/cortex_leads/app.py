import importlib
from pathlib import Path

from fastapi import FastAPI

from cortex_leads.config import get_settings

# (module, prefix): mounted only if the owning WP has landed.
_ROUTERS = [
    ("cortex_leads.ingest.api", "/ingest"),
    ("cortex_leads.review.api", "/review"),
    ("cortex_leads.supervisor.api", "/supervisor"),
    ("cortex_leads.review.facts_api", "/review"),  # WP9
    ("cortex_leads.staff_ui.routes", "/staff"),  # WP13
    ("cortex_leads.console.api", "/api/v1"),  # WP27: the main UI's JSON
    ("cortex_leads.admin.api", "/api/admin"),  # WP47: the platform admin page, its own sign-in
]


def create_app(web_dist: Path | None = None) -> FastAPI:
    get_settings()  # fail fast on missing/leaked secrets
    app = FastAPI(title="cortex-leads")
    from cortex_leads.audit import context as audit_context

    audit_context.install(app)  # ip / browser / request id for every audit line

    @app.middleware("http")
    async def harden(request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")  # the console is never framed
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"  # what the API says about people is never kept by a browser or a proxy
        return response
    for module, prefix in _ROUTERS:
        try:
            mod = importlib.import_module(module)
        except ModuleNotFoundError as e:
            if e.name and module.startswith(e.name):
                continue  # package not written yet; any other missing import is a real bug
            raise
        app.include_router(mod.router, prefix=prefix)

    from cortex_leads.console.spa import mount_spa

    mount_spa(app, web_dist)  # the built console, if there is one (web/dist)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
