import asyncio
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402

EXPECTED_TABLES = {
    "alembic_version",
    "document_analyses",
    "document_chunks",
    "documents",
    "knowledge_spaces",
    "users",
}
EXPECTED_HEAD = "005"
DISPOSABLE_DATABASE_PREFIX = "documind_migration_verify_"
LOCAL_DATABASE_HOSTS = {"127.0.0.1", "::1", "db", "localhost"}
PROTECTED_DATABASE_NAMES = {"postgres", "template0", "template1"}
source_database_url = make_url(settings.database_url)


def assert_safe_database_server() -> None:
    if source_database_url.host not in LOCAL_DATABASE_HOSTS:
        raise RuntimeError("Migration verification refuses non-local PostgreSQL servers")


def assert_disposable_database_name(database_name: str) -> None:
    expected_pattern = rf"{re.escape(DISPOSABLE_DATABASE_PREFIX)}[0-9a-f]{{32}}"
    if not re.fullmatch(expected_pattern, database_name):
        raise RuntimeError("Refusing to manage a database without the verification prefix")
    if database_name in PROTECTED_DATABASE_NAMES or database_name == source_database_url.database:
        raise RuntimeError("Refusing to manage a protected or configured database")


def disposable_database_url() -> tuple[URL, str]:
    assert_safe_database_server()
    database_name = f"{DISPOSABLE_DATABASE_PREFIX}{uuid.uuid4().hex}"
    assert_disposable_database_name(database_name)
    return source_database_url.set(database=database_name), database_name


def run_alembic(database_url: URL, *args: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url.render_as_string(hide_password=False)
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=environment,
        check=True,
    )


async def create_database(database_name: str) -> None:
    assert_safe_database_server()
    assert_disposable_database_name(database_name)
    admin_url = source_database_url.set(database="postgres")
    engine = create_async_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    finally:
        await engine.dispose()


async def drop_database(database_name: str) -> None:
    assert_safe_database_server()
    assert_disposable_database_name(database_name)
    admin_url = source_database_url.set(database="postgres")
    engine = create_async_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
    finally:
        await engine.dispose()


async def scalar_rows(database_url: URL, statement: str) -> set[str]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(statement))
            return {str(row[0]) for row in result}
    finally:
        await engine.dispose()


async def key_value_rows(database_url: URL, statement: str) -> dict[str, str]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(statement))
            return {str(row[0]): str(row[1]) for row in result}
    finally:
        await engine.dispose()


async def verify_head_schema(database_url: URL) -> None:
    tables = await scalar_rows(
        database_url,
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'",
    )
    if tables != EXPECTED_TABLES:
        raise RuntimeError(f"Unexpected tables at head: {sorted(tables)}")

    revision = await scalar_rows(database_url, "SELECT version_num FROM alembic_version")
    if revision != {EXPECTED_HEAD}:
        raise RuntimeError(f"Unexpected Alembic revision: {sorted(revision)}")

    constraints = await scalar_rows(
        database_url,
        "SELECT constraint_name FROM information_schema.table_constraints "
        "WHERE table_schema = 'public' "
        "AND table_name IN ('users', 'knowledge_spaces', 'documents', 'document_chunks', "
        "'document_analyses')",
    )
    required_constraints = {
        "knowledge_spaces_pkey",
        "knowledge_spaces_user_id_fkey",
        "documents_pkey",
        "documents_knowledge_space_id_fkey",
        "documents_storage_key_key",
        "document_chunks_pkey",
        "document_chunks_document_id_fkey",
        "uq_document_chunks_position",
        "document_analyses_pkey",
        "document_analyses_document_id_fkey",
        "uq_document_analyses_document_id",
        "users_email_key",
        "users_pkey",
    }
    if not required_constraints.issubset(constraints):
        missing = required_constraints - constraints
        raise RuntimeError(f"Missing constraints: {sorted(missing)}")

    delete_action = await scalar_rows(
        database_url,
        "SELECT delete_rule FROM information_schema.referential_constraints "
        "WHERE constraint_name IN ("
        "'knowledge_spaces_user_id_fkey', 'documents_knowledge_space_id_fkey', "
        "'document_chunks_document_id_fkey', 'document_analyses_document_id_fkey')",
    )
    if delete_action != {"CASCADE"}:
        raise RuntimeError(f"Unexpected FK delete action: {sorted(delete_action)}")

    indexes = await scalar_rows(
        database_url,
        "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'",
    )
    required_indexes = {
        "ix_knowledge_spaces_user_id",
        "ix_users_email",
        "ix_documents_knowledge_space_id",
        "ix_document_chunks_document_id",
        "ix_document_analyses_document_id",
        "documents_storage_key_key",
        "documents_pkey",
        "document_chunks_pkey",
        "document_analyses_pkey",
        "uq_document_chunks_position",
        "uq_document_analyses_document_id",
        "knowledge_spaces_pkey",
        "users_email_key",
        "users_pkey",
    }
    if not required_indexes.issubset(indexes):
        missing = required_indexes - indexes
        raise RuntimeError(f"Missing indexes: {sorted(missing)}")

    column_types = await key_value_rows(
        database_url,
        "SELECT table_name || '.' || column_name, data_type || ':' || is_nullable "
        "FROM information_schema.columns WHERE table_schema = 'public' "
        "AND table_name IN ('users', 'knowledge_spaces', 'documents', 'document_chunks', "
        "'document_analyses')",
    )
    required_columns = {
        "knowledge_spaces.id": "uuid:NO",
        "knowledge_spaces.name": "character varying:NO",
        "knowledge_spaces.user_id": "uuid:NO",
        "users.email": "character varying:NO",
        "users.hashed_password": "character varying:NO",
        "users.id": "uuid:NO",
        "users.is_active": "boolean:NO",
        "documents.id": "uuid:NO",
        "documents.knowledge_space_id": "uuid:NO",
        "documents.file_size": "bigint:NO",
        "documents.page_count": "integer:YES",
        "document_chunks.id": "uuid:NO",
        "document_chunks.document_id": "uuid:NO",
        "document_chunks.page_number": "integer:NO",
        "document_chunks.embedding": "USER-DEFINED:NO",
        "document_analyses.id": "uuid:NO",
        "document_analyses.document_id": "uuid:NO",
        "document_analyses.status": "character varying:NO",
        "document_analyses.document_type": "character varying:NO",
        "document_analyses.important_dates": "jsonb:NO",
        "document_analyses.key_facts": "jsonb:NO",
    }
    for column, expected in required_columns.items():
        if column_types.get(column) != expected:
            raise RuntimeError(f"Unexpected definition for {column}: {column_types.get(column)!r}")

    defaults = await key_value_rows(
        database_url,
        "SELECT table_name || '.' || column_name, column_default "
        "FROM information_schema.columns WHERE table_schema = 'public' "
        "AND column_default IS NOT NULL",
    )
    expected_defaults = {
        "knowledge_spaces.created_at": "now()",
        "knowledge_spaces.updated_at": "now()",
        "users.created_at": "now()",
        "users.is_active": "true",
        "users.updated_at": "now()",
        "documents.created_at": "now()",
        "documents.status": "'processing'::character varying",
        "documents.updated_at": "now()",
        "document_chunks.created_at": "now()",
        "document_analyses.created_at": "now()",
        "document_analyses.status": "'processing'::character varying",
        "document_analyses.document_type": "'unknown'::character varying",
        "document_analyses.updated_at": "now()",
        "document_analyses.important_dates": "'[]'::jsonb",
        "document_analyses.key_facts": "'[]'::jsonb",
    }
    for column, expected in expected_defaults.items():
        if defaults.get(column) != expected:
            raise RuntimeError(f"Unexpected default for {column}: {defaults.get(column)!r}")

    extensions = await scalar_rows(
        database_url,
        "SELECT extname FROM pg_extension WHERE extname = 'vector'",
    )
    if extensions != {"vector"}:
        raise RuntimeError("pgvector extension is not installed")

    vector_type = await scalar_rows(
        database_url,
        "SELECT format_type(a.atttypid, a.atttypmod) "
        "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
        "WHERE c.relname = 'document_chunks' AND a.attname = 'embedding'",
    )
    if vector_type != {"vector(384)"}:
        raise RuntimeError(f"Unexpected embedding type: {sorted(vector_type)}")


async def verify_base_schema(database_url: URL) -> None:
    tables = await scalar_rows(
        database_url,
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' "
        "AND table_name IN ('users', 'knowledge_spaces', 'documents', 'document_chunks')",
    )
    if tables:
        raise RuntimeError(f"Application tables remain at base: {sorted(tables)}")


async def main() -> None:
    database_url, database_name = disposable_database_url()
    print(f"Verifying migrations in disposable database: {database_name}")
    await create_database(database_name)
    try:
        run_alembic(database_url, "upgrade", "head")
        await verify_head_schema(database_url)
        run_alembic(database_url, "upgrade", "head")
        await verify_head_schema(database_url)
        run_alembic(database_url, "downgrade", "base")
        await verify_base_schema(database_url)
        run_alembic(database_url, "upgrade", "head")
        await verify_head_schema(database_url)
    finally:
        await drop_database(database_name)
    print("Migration verification passed: upgrade, idempotency, downgrade, and re-upgrade")


if __name__ == "__main__":
    asyncio.run(main())
