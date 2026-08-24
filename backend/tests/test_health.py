import logging

import pytest

from app.api import health as health_api
from app.config import settings
from app.observability import JsonFormatter, new_request_id, request_id_var


@pytest.mark.asyncio
async def test_health(async_client):
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_readiness_reports_database_reachable(async_client):
    response = await async_client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "reachable"


@pytest.mark.asyncio
async def test_readiness_skips_database_in_public_demo(async_client, monkeypatch):
    class _UnavailableEngine:
        def connect(self):
            raise AssertionError("public demo readiness must not connect to the database")

    monkeypatch.setattr(settings, "public_demo_mode", True)
    monkeypatch.setattr(health_api, "engine", _UnavailableEngine())

    response = await async_client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.1.0",
        "mode": "public-demo",
        "public_demo": True,
        "database": "not_required",
    }


@pytest.mark.asyncio
async def test_readiness_reports_database_unreachable(async_client, monkeypatch):
    class _UnavailableConnection:
        async def __aenter__(self):
            raise ConnectionError("database unavailable")

        async def __aexit__(self, exc_type, exc_value, traceback):
            return False

    class _UnavailableEngine:
        def connect(self):
            return _UnavailableConnection()

    monkeypatch.setattr(settings, "public_demo_mode", False)
    monkeypatch.setattr(health_api, "engine", _UnavailableEngine())

    response = await async_client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["database"] == "unreachable"


@pytest.mark.asyncio
async def test_every_response_carries_request_id(async_client):
    response = await async_client.get("/health")
    request_id = response.headers.get("X-Request-ID")
    assert request_id
    assert len(request_id) == 32


@pytest.mark.asyncio
async def test_supplied_request_id_is_honored_and_echoed(async_client):
    supplied = f"test-{new_request_id()}"
    response = await async_client.get("/health", headers={"X-Request-ID": supplied})
    assert response.headers["X-Request-ID"] == supplied


def test_json_formatter_includes_correlation_id():
    formatter = JsonFormatter()

    class _Record:
        pass

    import logging as std_logging

    record = std_logging.LogRecord(
        name="documind.test",
        level=std_logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    token = request_id_var.set("abc123")
    try:
        payload = formatter.format(record)
    finally:
        request_id_var.reset(token)

    assert '"message": "hello world"' in payload
    assert '"request_id": "abc123"' in payload


def test_json_formatter_never_includes_reserved_fields():
    import logging as std_logging

    formatter = JsonFormatter()
    record = std_logging.LogRecord(
        name="documind.test",
        level=std_logging.INFO,
        pathname="/etc/secrets/password.py",
        lineno=1,
        msg="event",
        args=None,
        exc_info=None,
    )
    record.__dict__.update({"document_name": "contract.pdf", "pathname": "/etc/secrets"})
    payload = formatter.format(record)
    assert "/etc/secrets" not in payload
    assert '"document_name": "contract.pdf"' in payload


def test_configure_logging_is_idempotent():
    from app.observability import configure_logging

    configure_logging()
    configure_logging()
    root = logging.getLogger()
    assert len(root.handlers) == 1
