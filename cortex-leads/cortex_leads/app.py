import importlib

from fastapi import FastAPI

from cortex_leads.config import get_settings

# (module, prefix): mounted only if the owning WP has landed.
_ROUTERS = [
    ("cortex_leads.ingest.api", "/ingest"),
    ("cortex_leads.review.api", "/review"),
    ("cortex_leads.supervisor.api", "/supervisor"),
    ("cortex_leads.review.facts_api", "/review"),  # WP9
    ("cortex_leads.staff_ui.routes", "/staff"),  # WP13
]


def create_app() -> FastAPI:
    get_settings()  # fail fast on missing/leaked secrets
    app = FastAPI(title="cortex-leads")
    for module, prefix in _ROUTERS:
        try:
            mod = importlib.import_module(module)
        except ModuleNotFoundError as e:
            if e.name and module.startswith(e.name):
                continue  # package not written yet; any other missing import is a real bug
            raise
        app.include_router(mod.router, prefix=prefix)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
