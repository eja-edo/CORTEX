import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import executions, workflows, webhooks, actions, system_workflows

_ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")


@asynccontextmanager
async def lifespan(application: FastAPI):
    from app.actions import action_registry  # noqa: F401
    from app.triggers.internal_event_listener import start_internal_event_listener
    from app.temporal.worker import start_worker_background
    listener_task = asyncio.create_task(start_internal_event_listener())
    worker_task = start_worker_background()

    yield
    listener_task.cancel()
    worker_task.cancel()
    try:
        await listener_task
    except asyncio.CancelledError:
        pass
    try:
        await worker_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Cortex Workflow Service",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workflows.router, prefix="/api/v1/workflows", tags=["workflows"])
app.include_router(executions.router, prefix="/api/v1/executions", tags=["executions"])
app.include_router(webhooks.router, prefix="/api/v1/webhooks", tags=["webhooks"])
app.include_router(actions.router, prefix="/api/v1/actions", tags=["actions"])
app.include_router(system_workflows.router, prefix="/api/v1/system-workflows", tags=["system-workflows"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "workflow_service"}
