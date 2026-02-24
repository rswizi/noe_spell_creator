import os
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("CORS_ORIGINS", "http://localhost")
os.environ.setdefault("MONGODB_URI", "mongomock://localhost")
os.environ.setdefault("ASSETS_MAX_UPLOAD_MB", "1")
os.environ.setdefault("WIKI_ENABLED", "true")
os.environ.setdefault("WIKI_REQUIRE_AUTH", "true")

from db_mongo import get_db
from main import app
from server.src.modules.authentification_helpers import SESSIONS, SESSION_ROLE_OVERRIDES


@pytest.fixture(autouse=True)
def clean_state():
    db = get_db()
    for name in db.list_collection_names():
        db.drop_collection(name)
    SESSIONS.clear()
    SESSION_ROLE_OVERRIDES.clear()
    yield
    SESSIONS.clear()
    SESSION_ROLE_OVERRIDES.clear()


@asynccontextmanager
async def wiki_client(
    auth_token: str | None = "test-token",
    role: str = "admin",
    username: str = "tester",
    wiki_role: str | None = None,
):
    headers: dict[str, str] = {}
    if auth_token:
        SESSIONS[auth_token] = (username, role)
        headers["Authorization"] = f"Bearer {auth_token}"
    if wiki_role:
        get_db()["users"].update_one(
            {"username": username},
            {"$set": {"username": username, "wiki_role": wiki_role}},
            upsert=True,
        )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=headers) as client:
        yield client
