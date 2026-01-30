import asyncio
import os
from contextlib import asynccontextmanager

import pytest
from httpx import AsyncClient, ASGITransport

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("API_TOKEN", "test-token")
os.environ.setdefault("CORS_ORIGINS", "http://localhost")
os.environ.setdefault("MONGODB_URI", "mongomock://localhost")
os.environ.setdefault("ASSETS_MAX_UPLOAD_MB", "1")

from server.src.modules.wiki_db import Base, engine
from main import app


@pytest.fixture(autouse=True)
def prepare_db():
    async def init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(init())
    yield
    async def teardown():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    asyncio.run(teardown())


@asynccontextmanager
async def wiki_client(auth_token: str | None = "test-token"):
    headers: dict[str, str] = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as client:
        yield client
