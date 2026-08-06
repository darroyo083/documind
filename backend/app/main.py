from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.actions import router as actions_router
from app.api.analysis import router as analysis_router
from app.api.auth import router as auth_router
from app.api.comparisons import router as comparisons_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.knowledge_spaces import router as knowledge_spaces_router
from app.api.reference import router as reference_router
from app.config import settings
from app.infrastructure import models as _models  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:4173",
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
app.include_router(reference_router)
