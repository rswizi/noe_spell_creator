import io

import pytest
from PIL import Image

from tests.conftest import wiki_client


@pytest.mark.asyncio
async def test_upload_requires_auth():
    async with wiki_client(auth_token=None) as client:
        resp = await client.post("/api/assets/upload", files={"file": ("test.png", b"x", "image/png")})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_upload_forbidden_for_viewer():
    async with wiki_client(role="user", wiki_role="viewer") as client:
        resp = await client.post("/api/assets/upload", files={"file": ("test.png", b"x", "image/png")})
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_upload_rejects_invalid_mime():
    async with wiki_client() as client:
        resp = await client.post("/api/assets/upload", files={"file": ("text.txt", b"text", "text/plain")})
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_rejects_oversize():
    big = b"x" * (2 * 1024 * 1024)
    async with wiki_client() as client:
        resp = await client.post("/api/assets/upload", files={"file": ("big.png", big, "image/png")})
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_upload_and_fetch():
    buf = io.BytesIO()
    Image.new("RGBA", (10, 10), (255, 0, 0, 255)).save(buf, format="PNG")
    data = buf.getvalue()
    async with wiki_client() as client:
        resp = await client.post("/api/assets/upload", files={"file": ("test.png", data, "image/png")})
        assert resp.status_code == 200
        asset = resp.json()
        assert asset["mime"] == "image/png"
        assert asset["width"] == 10
        assert asset["height"] == 10
        assert asset["size"] == len(data)

        get_resp = await client.get(asset["url"])
        assert get_resp.status_code == 200
        assert get_resp.headers["content-type"] == "image/png"
        assert "max-age=31536000" in get_resp.headers["cache-control"]
        assert get_resp.content == data
