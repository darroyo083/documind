import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.actions import router as actions_router
from app.api.analysis import router as analysis_router
from app.api.auth import router as auth_router
from app.api.comparisons import router as comparisons_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.intelligence import router as intelligence_router
from app.api.knowledge_spaces import router as knowledge_spaces_router
from app.api.public_demo import router as public_demo_router
from app.api.reference import router as reference_router
from app.api.search import router as search_router
from app.config import settings
from app.infrastructure import models as _models  # noqa: F401
from app.observability import (
    configure_logging,
    log_event,
    monotonic_ms,
    new_request_id,
    request_id_var,
)

logger = logging.getLogger("documind.request")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log_event(
        logger,
        logging.INFO,
        "startup",
        app_version=settings.app_version,
        public_demo_mode=settings.public_demo_mode,
        generation_provider=settings.generation_provider,
        embedding_provider=settings.embedding_provider,
        retrieval_mode=settings.retrieval_mode,
    )
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url=None if settings.public_demo_mode else "/docs",
    redoc_url=None if settings.public_demo_mode else "/redoc",
    openapi_url=None if settings.public_demo_mode else "/openapi.json",
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Attach a correlation ID to every request and log its outcome.

    The client-supplied ``X-Request-ID`` is honored (bounded length); paths and
    query strings are never logged, so credentials or document identifiers in
    URLs cannot leak into logs.
    """
    supplied = request.headers.get("X-Request-ID", "")
    request_id = supplied[:64] if supplied else new_request_id()
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    response = None
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
    finally:
        duration_ms = monotonic_ms(started)
        if request.url.path != "/health":
            status_code: object = getattr(response, "status_code", "unhandled_exception")
            level = logging.INFO
            if isinstance(status_code, int):
                if status_code >= 500:
                    level = logging.ERROR
                elif status_code >= 400:
                    level = logging.WARNING
            log_event(
                logger,
                level,
                "request",
                method=request.method,
                status=status_code,
                duration_ms=duration_ms,
            )
        request_id_var.reset(token)
    return response


@app.middleware("http")
async def public_demo_cost_guard(request: Request, call_next):
    """Reject every private mutation before auth, storage, or provider resolution."""
    if settings.public_demo_mode and request.method not in {"GET", "HEAD", "OPTIONS"}:
        allowed_demo_mutations = {"/public-demo/space/ask"}
        if request.url.path not in allowed_demo_mutations:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": (
                        "Public demo mode is read-only; live authentication, uploads, "
                        "mutations, and AI generation are disabled."
                    )
                },
            )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(knowledge_spaces_router)
app.include_router(documents_router)
app.include_router(analysis_router)
app.include_router(actions_router)
app.include_router(comparisons_router)
app.include_router(intelligence_router)
app.include_router(reference_router)
app.include_router(search_router)
app.include_router(public_demo_router)
