import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password
from app.infrastructure.models import KnowledgeSpace, User

SPACES_URL = "/knowledge-spaces"
REGISTER_URL = "/auth/register"


async def register_user(async_client: AsyncClient, email: str) -> str:
    resp = await async_client.post(
        REGISTER_URL,
        json={
            "email": email,
            "password": "TestPass1",
            "display_name": email.split("@")[0],
        },
    )
    return resp.json()["access_token"]


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_space(async_client: AsyncClient):
    token = await register_user(async_client, "create@test.com")
    resp = await async_client.post(
        SPACES_URL,
        json={"name": "My Space", "description": "Test description"},
        headers=auth_header(token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "My Space"
    assert data["description"] == "Test description"
    assert "id" in data


@pytest.mark.asyncio
async def test_create_space_minimal(async_client: AsyncClient):
    token = await register_user(async_client, "create-min@test.com")
    resp = await async_client.post(
        SPACES_URL,
        json={"name": "Minimal"},
        headers=auth_header(token),
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Minimal"
    assert resp.json()["description"] is None


@pytest.mark.asyncio
async def test_create_space_unauthenticated(async_client: AsyncClient):
    resp = await async_client.post(SPACES_URL, json={"name": "No Auth"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_space_blank_name(async_client: AsyncClient):
    token = await register_user(async_client, "blank-name@test.com")
    resp = await async_client.post(
        SPACES_URL,
        json={"name": "   ", "description": "blank"},
        headers=auth_header(token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_space_name_too_long(async_client: AsyncClient):
    token = await register_user(async_client, "long-name@test.com")
    resp = await async_client.post(
        SPACES_URL,
        json={"name": "a" * 201},
        headers=auth_header(token),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_own_spaces(async_client: AsyncClient):
    token = await register_user(async_client, "list-own@test.com")
    await async_client.post(SPACES_URL, json={"name": "Space A"}, headers=auth_header(token))
    await async_client.post(SPACES_URL, json={"name": "Space B"}, headers=auth_header(token))

    resp = await async_client.get(SPACES_URL, headers=auth_header(token))
    assert resp.status_code == 200
    names = [s["name"] for s in resp.json()]
    assert len(names) == 2
    assert "Space A" in names
    assert "Space B" in names


@pytest.mark.asyncio
async def test_list_only_own_spaces(async_client: AsyncClient):
    token_a = await register_user(async_client, "user-a@test.com")
    token_b = await register_user(async_client, "user-b@test.com")

    await async_client.post(SPACES_URL, json={"name": "A's Space"}, headers=auth_header(token_a))
    await async_client.post(SPACES_URL, json={"name": "B's Space"}, headers=auth_header(token_b))

    resp_a = await async_client.get(SPACES_URL, headers=auth_header(token_a))
    names_a = [s["name"] for s in resp_a.json()]
    assert names_a == ["A's Space"]

    resp_b = await async_client.get(SPACES_URL, headers=auth_header(token_b))
    names_b = [s["name"] for s in resp_b.json()]
    assert names_b == ["B's Space"]


@pytest.mark.asyncio
async def test_get_own_space(async_client: AsyncClient):
    token = await register_user(async_client, "get-own@test.com")
    created = (
        await async_client.post(
            SPACES_URL,
            json={"name": "Get Me"},
            headers=auth_header(token),
        )
    ).json()

    resp = await async_client.get(f"{SPACES_URL}/{created['id']}", headers=auth_header(token))
    assert resp.status_code == 200
    assert resp.json()["name"] == "Get Me"


@pytest.mark.asyncio
async def test_get_others_space(async_client: AsyncClient, db_session: AsyncSession):
    owner_user = User(
        email="owner@test.com",
        hashed_password=hash_password("TestPass1"),
        display_name="Owner",
    )
    db_session.add(owner_user)
    await db_session.commit()
    await db_session.refresh(owner_user)

    space = KnowledgeSpace(user_id=owner_user.id, name="Secret Space")
    db_session.add(space)
    await db_session.commit()
    await db_session.refresh(space)

    intruder_token = await register_user(async_client, "intruder@test.com")
    resp = await async_client.get(f"{SPACES_URL}/{space.id}", headers=auth_header(intruder_token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_own_space(async_client: AsyncClient):
    token = await register_user(async_client, "upd-own@test.com")
    created = (
        await async_client.post(
            SPACES_URL,
            json={"name": "Before", "description": "Old"},
            headers=auth_header(token),
        )
    ).json()

    resp = await async_client.patch(
        f"{SPACES_URL}/{created['id']}",
        json={"name": "After", "description": "New"},
        headers=auth_header(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "After"
    assert data["description"] == "New"


@pytest.mark.asyncio
async def test_update_can_clear_description(async_client: AsyncClient):
    token = await register_user(async_client, "clear-description@test.com")
    created = (
        await async_client.post(
            SPACES_URL,
            json={"name": "Clear Description", "description": "Remove me"},
            headers=auth_header(token),
        )
    ).json()

    resp = await async_client.patch(
        f"{SPACES_URL}/{created['id']}",
        json={"description": None},
        headers=auth_header(token),
    )
    assert resp.status_code == 200
    assert resp.json()["description"] is None


@pytest.mark.asyncio
async def test_update_others_space(async_client: AsyncClient, db_session: AsyncSession):
    owner_user = User(
        email="owner2@test.com",
        hashed_password=hash_password("TestPass1"),
        display_name="Owner2",
    )
    db_session.add(owner_user)
    await db_session.commit()
    await db_session.refresh(owner_user)

    space = KnowledgeSpace(user_id=owner_user.id, name="Their Space")
    db_session.add(space)
    await db_session.commit()
    await db_session.refresh(space)

    intruder_token = await register_user(async_client, "intruder2@test.com")
    resp = await async_client.patch(
        f"{SPACES_URL}/{space.id}",
        json={"name": "Mine Now"},
        headers=auth_header(intruder_token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_own_space(async_client: AsyncClient):
    token = await register_user(async_client, "del-own@test.com")
    created = (
        await async_client.post(
            SPACES_URL,
            json={"name": "Delete Me"},
            headers=auth_header(token),
        )
    ).json()

    resp = await async_client.delete(f"{SPACES_URL}/{created['id']}", headers=auth_header(token))
    assert resp.status_code == 204

    get_resp = await async_client.get(f"{SPACES_URL}/{created['id']}", headers=auth_header(token))
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_others_space(async_client: AsyncClient, db_session: AsyncSession):
    owner_user = User(
        email="owner3@test.com",
        hashed_password=hash_password("TestPass1"),
        display_name="Owner3",
    )
    db_session.add(owner_user)
    await db_session.commit()
    await db_session.refresh(owner_user)

    space = KnowledgeSpace(user_id=owner_user.id, name="Not Mine")
    db_session.add(space)
    await db_session.commit()
    await db_session.refresh(space)

    intruder_token = await register_user(async_client, "intruder3@test.com")
    resp = await async_client.delete(
        f"{SPACES_URL}/{space.id}", headers=auth_header(intruder_token)
    )
    assert resp.status_code == 404
