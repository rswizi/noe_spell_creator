import pytest

from tests.conftest import wiki_client
from tests.helpers import create_page


@pytest.mark.asyncio
async def test_create_and_get_page():
    async with wiki_client() as client:
        payload = {"title": "Solo Page", "slug": "solo-page", "doc_json": {"type": "doc", "content": []}}
        response = await client.post("/api/wiki/pages", json=payload)
        assert response.status_code == 200
        created = response.json()
        assert created["slug"] == "solo-page"

        read = await client.get(f"/api/wiki/pages/{created['id']}")
        assert read.status_code == 200
        assert read.json()["title"] == "Solo Page"


@pytest.mark.asyncio
async def test_list_public_read():
    async with wiki_client() as client:
        await create_page(client, "List A", "list-a")
        await create_page(client, "List B", "list-b")
    async with wiki_client(auth_token=None) as client:
        response = await client.get("/api/wiki/pages?limit=5")
        assert response.status_code == 200
        payload = response.json()
        assert payload["items"]
        assert payload["total"] >= 2


@pytest.mark.asyncio
async def test_resolve_public_access():
    async with wiki_client() as client:
        await create_page(client, "Resolve Entry", "resolve-entry")
    async with wiki_client(auth_token=None) as client:
        response = await client.get("/api/wiki/resolve?query=resolve")
        assert response.status_code == 200
        assert response.json()


@pytest.mark.asyncio
async def test_write_requires_auth():
    async with wiki_client(auth_token=None) as client:
        payload = {"title": "Needs Auth", "slug": "needs-auth", "doc_json": {"type": "doc", "content": []}}
        response = await client.post("/api/wiki/pages", json=payload)
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_revisions_require_auth():
    async with wiki_client() as client:
        created = await create_page(client, "Rev Locked", "rev-locked")
    async with wiki_client(auth_token=None) as client:
        response = await client.post(f"/api/wiki/pages/{created['id']}/revisions")
        assert response.status_code == 401
