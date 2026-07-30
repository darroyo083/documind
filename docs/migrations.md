# Run and verify database migrations

Alembic is the only supported way to create or change DocuMind's application schema. Do not create application tables manually and do not use SQLAlchemy `create_all()` as a migration substitute.

## Canonical workflow

Run Alembic from the backend container so it uses Docker Compose's `DATABASE_URL` and connects to the `db` service:

```bash
docker compose up -d db backend
docker compose exec backend alembic upgrade head
```

Inspect migration state:

```bash
docker compose exec backend alembic current
docker compose exec backend alembic heads
docker compose exec backend alembic history
```

Downgrade one revision or return to base:

```bash
docker compose exec backend alembic downgrade -1
docker compose exec backend alembic downgrade base
```

## Verify the complete lifecycle

The verification script creates a uniquely named disposable PostgreSQL database, upgrades it twice, downgrades to base, upgrades again, verifies the schema, and drops the database:

```bash
docker compose exec backend python scripts/verify_migrations.py
```

The configured PostgreSQL user must be allowed to create and drop databases. The local Docker Compose user and the CI service user have that permission.

## Run backend tests

Tests create and remove their own uniquely named PostgreSQL database. They never create or drop application tables in the development database:

```bash
docker compose exec backend pytest --cov -v
```

## Reset local development safely

Only reset the Docker volume when all local DocuMind data can be discarded:

```bash
docker compose down -v
docker compose up -d db backend
docker compose exec backend alembic upgrade head
```

This deletes the complete local PostgreSQL volume. Never run it against a shared or production environment.
