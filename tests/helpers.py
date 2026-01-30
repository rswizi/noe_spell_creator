async def create_page(client, title: str, slug: str):
    payload = {"title": title, "slug": slug, "doc_json": {"type": "doc", "content": []}}
    resp = await client.post("/api/wiki/pages", json=payload)
    resp.raise_for_status()
    return resp.json()
