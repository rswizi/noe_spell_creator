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
        assert created["category_id"] == "general"
        assert created["status"] == "draft"

        read = await client.get(f"/api/wiki/pages/{created['id']}")
        assert read.status_code == 200
        assert read.json()["title"] == "Solo Page"


@pytest.mark.asyncio
async def test_read_requires_auth_by_default():
    async with wiki_client() as client:
        await create_page(client, "List A", "list-a")
    async with wiki_client(auth_token=None) as client:
        response = await client.get("/api/wiki/pages?limit=5")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_writer_can_create_but_cannot_manage_categories():
    async with wiki_client(role="moderator") as client:
        created = await create_page(client, "Writer Page", "writer-page")
        assert created["id"]
        create_cat = await client.post("/api/wiki/categories", json={"key": "places", "label": "Places"})
        assert create_cat.status_code == 403


@pytest.mark.asyncio
async def test_category_crud_admin_only():
    async with wiki_client() as client:
        created = await client.post("/api/wiki/categories", json={"key": "people", "label": "People", "sort_order": 2})
        assert created.status_code == 200
        payload = created.json()
        assert payload["id"] == "people"
        assert payload["slug"] == "people"

        listed = await client.get("/api/wiki/categories")
        assert listed.status_code == 200
        ids = [row["id"] for row in listed.json()]
        assert "people" in ids

        updated = await client.put("/api/wiki/categories/people", json={"label": "Characters"})
        assert updated.status_code == 200
        assert updated.json()["label"] == "Characters"

        removed = await client.delete("/api/wiki/categories/people")
        assert removed.status_code == 200


@pytest.mark.asyncio
async def test_page_filters_and_metadata():
    async with wiki_client() as client:
        await client.post("/api/wiki/categories", json={"key": "lore", "label": "Lore"})
        await client.post(
            "/api/wiki/pages",
            json={
                "title": "Page One",
                "slug": "page-one",
                "category_id": "lore",
                "status": "published",
                "tags": ["alpha", "beta"],
                "summary": "One",
                "doc_json": {"type": "doc", "content": []},
            },
        )
        await client.post(
            "/api/wiki/pages",
            json={
                "title": "Page Two",
                "slug": "page-two",
                "category_id": "general",
                "status": "draft",
                "tags": ["beta"],
                "doc_json": {"type": "doc", "content": []},
            },
        )

        by_category = await client.get("/api/wiki/pages?category_id=lore")
        assert by_category.status_code == 200
        assert by_category.json()["total"] == 1

        by_status = await client.get("/api/wiki/pages?status=published")
        assert by_status.status_code == 200
        assert by_status.json()["total"] == 1

        by_tag = await client.get("/api/wiki/pages?tag=beta")
        assert by_tag.status_code == 200
        assert by_tag.json()["total"] == 2


@pytest.mark.asyncio
async def test_links_backlinks_and_relations():
    async with wiki_client() as client:
        target = await create_page(client, "Target", "target")
        source_payload = {
            "title": "Source",
            "slug": "source",
            "doc_json": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "to target",
                                "marks": [
                                    {
                                        "type": "link",
                                        "attrs": {
                                            "href": "/wiki/slug/target",
                                            "pageSlug": "target",
                                            "pageId": target["id"],
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
        }
        source_resp = await client.post("/api/wiki/pages", json=source_payload)
        assert source_resp.status_code == 200
        source = source_resp.json()

        links = await client.get(f"/api/wiki/pages/{source['id']}/links")
        assert links.status_code == 200
        assert len(links.json()) == 1

        backlinks = await client.get(f"/api/wiki/pages/{target['id']}/backlinks")
        assert backlinks.status_code == 200
        assert backlinks.json()

        relation = await client.post(
            f"/api/wiki/pages/{source['id']}/relations",
            json={"to_page_id": target["id"], "relation_type": "related"},
        )
        assert relation.status_code == 200

        relation_list = await client.get(f"/api/wiki/pages/{source['id']}/relations")
        assert relation_list.status_code == 200
        assert relation_list.json()

        deleted = await client.delete(f"/api/wiki/relations/{relation.json()['id']}")
        assert deleted.status_code == 200


@pytest.mark.asyncio
async def test_acl_override_blocks_viewer():
    async with wiki_client() as admin_client:
        created = await create_page(admin_client, "ACL Page", "acl-page")
        acl = await admin_client.put(
            f"/api/wiki/pages/{created['id']}/acl",
            json={"acl_override": True, "view_roles": ["editor", "admin"], "edit_roles": ["admin"]},
        )
        assert acl.status_code == 200

    async with wiki_client(role="user", wiki_role="viewer") as viewer_client:
        read = await viewer_client.get(f"/api/wiki/pages/{created['id']}")
        assert read.status_code == 403


@pytest.mark.asyncio
async def test_write_requires_auth():
    async with wiki_client(auth_token=None) as client:
        payload = {"title": "Needs Auth", "slug": "needs-auth", "doc_json": {"type": "doc", "content": []}}
        response = await client.post("/api/wiki/pages", json=payload)
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_templates_crud_and_page_entity_type_filter():
    async with wiki_client() as client:
        tpl = await client.post(
            "/api/wiki/templates",
            json={"key": "npc", "label": "NPC", "fields": {"rank": "A"}},
        )
        assert tpl.status_code == 200
        assert tpl.json()["id"] == "npc"

        pages = [
            {
                "title": "NPC One",
                "slug": "npc-one",
                "entity_type": "npc",
                "template_id": "npc",
                "fields": {"rank": "S"},
                "doc_json": {"type": "doc", "content": []},
            },
            {
                "title": "Location One",
                "slug": "location-one",
                "entity_type": "location",
                "doc_json": {"type": "doc", "content": []},
            },
        ]
        for payload in pages:
            resp = await client.post("/api/wiki/pages", json=payload)
            assert resp.status_code == 200

        filtered = await client.get("/api/wiki/pages?entity_type=npc")
        assert filtered.status_code == 200
        assert filtered.json()["total"] == 1
        assert filtered.json()["items"][0]["entity_type"] == "npc"
        assert filtered.json()["items"][0]["fields"]["rank"] == "S"


@pytest.mark.asyncio
async def test_template_default_fields_applied_on_create():
    async with wiki_client() as client:
        tpl = await client.post(
            "/api/wiki/templates",
            json={"key": "artifact", "label": "Artifact", "fields": {"rarity": "legendary", "tier": 3}},
        )
        assert tpl.status_code == 200
        created = await client.post(
            "/api/wiki/pages",
            json={
                "title": "Artifact One",
                "slug": "artifact-one",
                "entity_type": "item",
                "template_id": "artifact",
                "doc_json": {"type": "doc", "content": []},
            },
        )
        assert created.status_code == 200
        payload = created.json()
        assert payload["fields"]["rarity"] == "legendary"
        assert payload["fields"]["tier"] == 3


@pytest.mark.asyncio
async def test_patch_fields_and_restore_revision():
    async with wiki_client() as client:
        created = await create_page(client, "Revision Page", "revision-page")
        patched = await client.patch(
            f"/api/wiki/pages/{created['id']}/fields",
            json={"fields": {"hp": 10, "class": "warrior"}},
        )
        assert patched.status_code == 200
        assert patched.json()["fields"]["hp"] == 10

        updated = await client.put(
            f"/api/wiki/pages/{created['id']}",
            json={
                "title": "Revision Page Updated",
                "slug": "revision-page-updated",
                "doc_json": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "v2"}]}]},
            },
        )
        assert updated.status_code == 200

        revision = await client.post(f"/api/wiki/pages/{created['id']}/revisions")
        assert revision.status_code == 200
        revision_id = revision.json()["id"]

        restored = await client.post(f"/api/wiki/pages/{created['id']}/revisions/{revision_id}/restore")
        assert restored.status_code == 200
        assert restored.json()["title"] == updated.json()["title"]


@pytest.mark.asyncio
async def test_delete_page_and_identity_endpoint():
    async with wiki_client() as client:
        identity = await client.get("/api/wiki/me")
        assert identity.status_code == 200
        assert identity.json()["wiki_role"] == "admin"

        created = await create_page(client, "Delete Me", "delete-me")
        deleted = await client.delete(f"/api/wiki/pages/{created['id']}")
        assert deleted.status_code == 200
        assert deleted.json()["ok"] is True

        read = await client.get(f"/api/wiki/pages/{created['id']}")
        assert read.status_code == 404


@pytest.mark.asyncio
async def test_page_context_returns_enriched_references():
    async with wiki_client() as client:
        target = await create_page(client, "Target Two", "target-two")
        source_resp = await client.post(
            "/api/wiki/pages",
            json={
                "title": "Source Two",
                "slug": "source-two",
                "doc_json": {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "linked",
                                    "marks": [
                                        {
                                            "type": "link",
                                            "attrs": {"href": "/wiki/slug/target-two", "pageSlug": "target-two", "pageId": target["id"]},
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
            },
        )
        assert source_resp.status_code == 200
        source = source_resp.json()
        rel = await client.post(
            f"/api/wiki/pages/{source['id']}/relations",
            json={"to_page_id": target["id"], "relation_type": "knows"},
        )
        assert rel.status_code == 200

        context = await client.get(f"/api/wiki/pages/{target['id']}/context")
        assert context.status_code == 200
        payload = context.json()
        assert payload["page"]["id"] == target["id"]
        assert payload["backlinks"]
        assert payload["backlinks"][0]["from_page"]["title"] == "Source Two"
        assert payload["relations"]
