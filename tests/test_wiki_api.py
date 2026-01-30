import asyncio
import os
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("API_TOKEN", "test-token")
os.environ.setdefault("CORS_ORIGINS", "http://localhost")

from contextlib import asynccontextmanager
from httpx import AsyncClient, ASGITransport
from server.src.modules.wiki_db import Base, engine
from main import app


def _init_db():
    async def _():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(_())


def _teardown_db():
    async def _():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    asyncio.run(_())


@pytest.fixture
def prepare_db():
    _init_db()
    yield
    _teardown_db()


@asynccontextmanager
async def wiki_client(auth_token: str | None = "test-token"):
    headers: dict[str, str] = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as client:
        yield client


@pytest.mark.asyncio
async def test_create_and_get_page(prepare_db):
    payload = {
        "title": "Test Page",
        "slug": "test-page",
        "doc_json": {"content": [{"type": "paragraph", "text": "Hello"}]},
    }
    async with wiki_client() as client:
        response = await client.post("/api/wiki/pages", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["slug"] == "test-page"

        get_resp = await client.get(f"/api/wiki/pages/{data['id']}")
        assert get_resp.status_code == 200
        assert get_resp.json()["title"] == "Test Page"


@pytest.mark.asyncio
async def test_slug_validation(prepare_db):
    async with wiki_client() as client:
        response = await client.post("/api/wiki/pages", json={"title": "Bad", "slug": "Bad Slug", "doc_json": {}})
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_update_page(prepare_db):
    payload = {
        "title": "Update Page",
        "slug": "update-page",
        "doc_json": {"content": []},
    }
    async with wiki_client() as client:
        response = await client.post("/api/wiki/pages", json=payload)
        pid = response.json()["id"]

        update = {"title": "Updated", "slug": "updated-page", "doc_json": {"content": [{"type": "paragraph", "text": "New"}]}}
        up_res = await client.put(f"/api/wiki/pages/{pid}", json=update)
        assert up_res.status_code == 200
        assert up_res.json()["slug"] == "updated-page"


@pytest.mark.asyncio
async def test_list_pages(prepare_db):
    async with wiki_client() as client:
        response = await client.get("/api/wiki/pages?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data


@pytest.mark.asyncio
async def test_revisions(prepare_db):
    payload = {"title": "Rev Page", "slug": "rev-page", "doc_json": {"abc": 1}}
    async with wiki_client() as client:
        resp = await client.post("/api/wiki/pages", json=payload)
        pid = resp.json()["id"]

        create_resp = await client.post(f"/api/wiki/pages/{pid}/revisions")
        assert create_resp.status_code == 200
        list_resp = await client.get(f"/api/wiki/pages/{pid}/revisions")
        assert list_resp.status_code == 200
        assert len(list_resp.json()) >= 1


@pytest.mark.asyncio
async def test_auth_failure():
    async with wiki_client(auth_token=None) as ac:
        resp = await ac.get("/api/wiki/pages")
        assert resp.status_code == 401
