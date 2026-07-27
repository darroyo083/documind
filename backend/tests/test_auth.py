from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from jose import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token, hash_password
from app.config import settings
from app.infrastructure.models import User

REGISTER_URL = "/auth/register"
LOGIN_URL = "/auth/login"
ME_URL = "/auth/me"

VALID_EMAIL = "test@example.com"
VALID_PASSWORD = "ValidPass1"
VALID_NAME = "Test User"


def expired_token(user_id: str) -> str:
    expire = datetime.now(UTC) - timedelta(hours=1)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


@pytest.mark.asyncio
async def test_register_success(async_client: AsyncClient, db_session: AsyncSession):
    response = await async_client.post(
        REGISTER_URL,
        json={
            "email": VALID_EMAIL,
            "password": VALID_PASSWORD,
            "display_name": VALID_NAME,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

    result = await db_session.execute(select(User).where(User.email == VALID_EMAIL))
    user = result.scalar_one_or_none()
    assert user is not None
    assert user.display_name == VALID_NAME
    assert user.email == VALID_EMAIL


@pytest.mark.asyncio
async def test_register_duplicate_email(async_client: AsyncClient):
    await async_client.post(
        REGISTER_URL,
        json={
            "email": "dup@example.com",
            "password": VALID_PASSWORD,
            "display_name": "First",
        },
    )
    response = await async_client.post(
        REGISTER_URL,
        json={
            "email": "dup@example.com",
            "password": "OtherPass1",
            "display_name": "Second",
        },
    )
    assert response.status_code == 409
    assert "already registered" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_register_invalid_password(async_client: AsyncClient):
    response = await async_client.post(
        REGISTER_URL,
        json={
            "email": "weak@example.com",
            "password": "short",
            "display_name": "Weak",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_invalid_email(async_client: AsyncClient):
    response = await async_client.post(
        REGISTER_URL,
        json={
            "email": "not-an-email",
            "password": VALID_PASSWORD,
            "display_name": "Bad Email",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_success(async_client: AsyncClient):
    await async_client.post(
        REGISTER_URL,
        json={
            "email": "login-test@example.com",
            "password": VALID_PASSWORD,
            "display_name": "Login Test",
        },
    )
    response = await async_client.post(
        LOGIN_URL,
        json={"email": "login-test@example.com", "password": VALID_PASSWORD},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(async_client: AsyncClient):
    await async_client.post(
        REGISTER_URL,
        json={
            "email": "wrong-pass@example.com",
            "password": VALID_PASSWORD,
            "display_name": "Wrong Pass",
        },
    )
    response = await async_client.post(
        LOGIN_URL,
        json={
            "email": "wrong-pass@example.com",
            "password": "WrongPass1",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_email(async_client: AsyncClient):
    response = await async_client.post(
        LOGIN_URL,
        json={
            "email": "nobody@example.com",
            "password": VALID_PASSWORD,
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_no_token(async_client: AsyncClient):
    response = await async_client.get(ME_URL)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_invalid_token(async_client: AsyncClient):
    response = await async_client.get(
        ME_URL, headers={"Authorization": "Bearer invalid-token-here"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_valid_token(async_client: AsyncClient, db_session: AsyncSession):
    user = User(
        email="me-test@example.com",
        hashed_password=hash_password(VALID_PASSWORD),
        display_name="Me Test",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = create_access_token(user.id)
    response = await async_client.get(
        ME_URL,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "me-test@example.com"
    assert data["display_name"] == "Me Test"
    assert data["id"] == str(user.id)


@pytest.mark.asyncio
async def test_me_expired_token(async_client: AsyncClient, db_session: AsyncSession):
    user = User(
        email="expired@example.com",
        hashed_password=hash_password(VALID_PASSWORD),
        display_name="Expired",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = expired_token(str(user.id))
    response = await async_client.get(
        ME_URL,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401
