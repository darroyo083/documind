import asyncio
import os
import re
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

DISPOSABLE_DATABASE_PREFIX = "documind_test_"
LOCAL_DATABASE_HOSTS = {"127.0.0.1", "::1", "db", "localhost"}
PROTECTED_DATABASE_NAMES = {"postgres", "template0", "template1"}
DEFAULT_DATABASE_URL = "postgresql+asyncpg://documind:documind@localhost:5432/documind"

source_database_url = make_url(os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
test_database_name = f"{DISPOSABLE_DATABASE_PREFIX}{uuid.uuid4().hex}"


def _assert_safe_database_server() -> None:
    if source_database_url.host not in LOCAL_DATABASE_HOSTS:
        raise RuntimeError("Tests refuse to create databases on a non-local PostgreSQL server")


def _assert_disposable_database_name(database_name: str) -> None:
    expected_pattern = rf"{re.escape(DISPOSABLE_DATABASE_PREFIX)}[0-9a-f]{{32}}"
    if not re.fullmatch(expected_pattern, database_name):
        raise RuntimeError("Refusing to manage a database without the disposable test prefix")
    if database_name in PROTECTED_DATABASE_NAMES or database_name == source_database_url.database:
        raise RuntimeError("Refusing to manage a protected or configured database")


_assert_safe_database_server()
_assert_disposable_database_name(test_database_name)
test_database_url = source_database_url.set(database=test_database_name)
os.environ["DATABASE_URL"] = test_database_url.render_as_string(hide_password=False)

from app.config import settings  # noqa: E402
from app.infrastructure.database import Base, get_db  # noqa: E402
from app.infrastructure.database import engine as application_engine  # noqa: E402
from app.main import app  # noqa: E402

if make_url(settings.database_url) != test_database_url:
    raise RuntimeError("Application settings did not load the disposable test database URL")
if application_engine.url != test_database_url:
    raise RuntimeError("Application engine did not bind to the disposable test database")


def _admin_engine() -> AsyncEngine:
    admin_url = source_database_url.set(database="postgres")
    return create_async_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_engine():
    _assert_disposable_database_name(test_database_name)
    admin_engine = _admin_engine()
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    database_created = False
    try:
        async with admin_engine.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{test_database_name}"'))
        database_created = True

        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
        yield engine
    finally:
        await engine.dispose()
        if database_created:
            _assert_disposable_database_name(test_database_name)
            async with admin_engine.connect() as conn:
                await conn.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                    ),
                    {"database_name": test_database_name},
                )
                await conn.execute(text(f'DROP DATABASE "{test_database_name}"'))
        await admin_engine.dispose()


@pytest.fixture
async def db_session(test_engine):
    factory = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def async_client(db_session):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
