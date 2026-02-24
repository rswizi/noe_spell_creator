from __future__ import annotations

import re
from uuid import uuid4
from typing import Any

from pymongo import ASCENDING, DESCENDING

from db_mongo import get_db
from settings import settings
from server.src.modules.wiki_config import get_wiki_settings
from server.src.modules.wiki_service import (
    build_page_view_filter,
    extract_internal_links,
    normalize_acl,
    normalize_category_id,
    normalize_entity_fields,
    normalize_entity_type,
    normalize_slug,
    normalize_status,
    normalize_summary,
    normalize_tags,
    plain_text_from_doc,
    utc_now,
)


WIKI_CATEGORIES_COL = "wiki_categories"
WIKI_PAGES_COL = "wiki_pages"
WIKI_PAGE_CONTENT_COL = "wiki_page_content"
WIKI_PAGE_REVISIONS_COL = "wiki_page_revisions"
WIKI_LINKS_COL = "wiki_links"
WIKI_RELATIONS_COL = "wiki_relations"
WIKI_ASSETS_COL = "wiki_assets"
WIKI_TEMPLATES_COL = "wiki_entity_templates"


def _is_mock() -> bool:
    return str(settings.mongodb_uri or "").startswith("mongomock://")


def _collection_exists(db, name: str) -> bool:
    try:
        items = list(db.list_collection_names())
        return name in items
    except Exception:
        return False


def _validator_for(name: str) -> dict[str, Any]:
    acl_schema = {
        "bsonType": "object",
        "additionalProperties": False,
        "properties": {
            "view_roles": {"bsonType": "array", "items": {"enum": ["viewer", "editor", "admin"]}},
            "edit_roles": {"bsonType": "array", "items": {"enum": ["viewer", "editor", "admin"]}},
        },
    }
    if name == WIKI_CATEGORIES_COL:
        return {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["id", "key", "label", "slug", "sort_order", "created_at", "updated_at"],
                "properties": {
                    "id": {"bsonType": "string"},
                    "key": {"bsonType": "string"},
                    "label": {"bsonType": "string"},
                    "slug": {"bsonType": "string"},
                    "icon": {"bsonType": ["string", "null"]},
                    "sort_order": {"bsonType": "int"},
                    "created_at": {"bsonType": ["date", "string"]},
                    "updated_at": {"bsonType": ["date", "string"]},
                },
            }
        }
    if name == WIKI_PAGES_COL:
        return {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["id", "title", "slug", "category_id", "status", "version", "created_at", "updated_at"],
                "properties": {
                    "id": {"bsonType": "string"},
                    "title": {"bsonType": "string"},
                    "slug": {"bsonType": "string"},
                    "category_id": {"bsonType": "string"},
                    "entity_type": {"bsonType": ["string", "null"]},
                    "template_id": {"bsonType": ["string", "null"]},
                    "fields": {"bsonType": ["object", "null"]},
                    "summary": {"bsonType": ["string", "null"]},
                    "tags": {"bsonType": ["array", "null"]},
                    "status": {"enum": ["draft", "published", "archived"]},
                    "created_by": {"bsonType": ["string", "null"]},
                    "updated_by": {"bsonType": ["string", "null"]},
                    "version": {"bsonType": "int"},
                    "acl_override": {"bsonType": ["bool", "null"]},
                    "acl": acl_schema,
                    "created_at": {"bsonType": ["date", "string"]},
                    "updated_at": {"bsonType": ["date", "string"]},
                },
            }
        }
    if name == WIKI_PAGE_CONTENT_COL:
        return {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["page_id", "doc_json", "plain_text", "version", "updated_at"],
                "properties": {
                    "page_id": {"bsonType": "string"},
                    "doc_json": {"bsonType": ["object", "array"]},
                    "plain_text": {"bsonType": ["string", "null"]},
                    "toc_snapshot": {"bsonType": ["array", "null"]},
                    "version": {"bsonType": "int"},
                    "updated_at": {"bsonType": ["date", "string"]},
                },
            }
        }
    if name == WIKI_PAGE_REVISIONS_COL:
        return {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["id", "page_id", "version", "doc_json", "title", "slug", "saved_at"],
                "properties": {
                    "id": {"bsonType": "string"},
                    "page_id": {"bsonType": "string"},
                    "version": {"bsonType": "int"},
                    "doc_json": {"bsonType": ["object", "array"]},
                    "title": {"bsonType": "string"},
                    "slug": {"bsonType": "string"},
                    "saved_by": {"bsonType": ["string", "null"]},
                    "saved_at": {"bsonType": ["date", "string"]},
                },
            }
        }
    if name == WIKI_LINKS_COL:
        return {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["id", "from_page_id", "created_at"],
                "properties": {
                    "id": {"bsonType": "string"},
                    "from_page_id": {"bsonType": "string"},
                    "to_page_id": {"bsonType": ["string", "null"]},
                    "to_page_slug": {"bsonType": ["string", "null"]},
                    "fragment": {"bsonType": ["string", "null"]},
                    "text": {"bsonType": ["string", "null"]},
                    "created_at": {"bsonType": ["date", "string"]},
                },
            }
        }
    if name == WIKI_RELATIONS_COL:
        return {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["id", "from_page_id", "to_page_id", "relation_type", "created_at"],
                "properties": {
                    "id": {"bsonType": "string"},
                    "from_page_id": {"bsonType": "string"},
                    "to_page_id": {"bsonType": "string"},
                    "relation_type": {"bsonType": "string"},
                    "note": {"bsonType": ["string", "null"]},
                    "created_at": {"bsonType": ["date", "string"]},
                },
            }
        }
    if name == WIKI_ASSETS_COL:
        return {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["asset_id", "r2_key", "mime", "size", "created_at"],
                "properties": {
                    "asset_id": {"bsonType": "string"},
                    "r2_key": {"bsonType": "string"},
                    "page_id": {"bsonType": ["string", "null"]},
                    "mime": {"bsonType": "string"},
                    "size": {"bsonType": "int"},
                    "width": {"bsonType": ["int", "null"]},
                    "height": {"bsonType": ["int", "null"]},
                    "usage_type": {"bsonType": ["string", "null"]},
                    "created_by": {"bsonType": ["string", "null"]},
                    "created_at": {"bsonType": ["date", "string"]},
                },
            }
        }
    if name == WIKI_TEMPLATES_COL:
        return {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["id", "key", "label", "fields", "created_at", "updated_at"],
                "properties": {
                    "id": {"bsonType": "string"},
                    "key": {"bsonType": "string"},
                    "label": {"bsonType": "string"},
                    "description": {"bsonType": ["string", "null"]},
                    "fields": {"bsonType": "object"},
                    "created_at": {"bsonType": ["date", "string"]},
                    "updated_at": {"bsonType": ["date", "string"]},
                },
            }
        }
    return {}


def _ensure_collection_with_validator(db, name: str) -> None:
    if _collection_exists(db, name):
        if _is_mock():
            return
        validator = _validator_for(name)
        if not validator:
            return
        try:
            db.command({"collMod": name, "validator": validator, "validationLevel": "moderate"})
        except Exception:
            return
        return
    validator = _validator_for(name)
    try:
        if _is_mock() or not validator:
            db.create_collection(name)
        else:
            db.create_collection(name, validator=validator, validationLevel="moderate")
    except Exception:
        try:
            db[name]
        except Exception:
            pass


def ensure_wiki_collections_and_indexes() -> None:
    cfg = get_wiki_settings()
    if not cfg.enabled:
        return
    db = get_db()
    names = (
        WIKI_CATEGORIES_COL,
        WIKI_PAGES_COL,
        WIKI_PAGE_CONTENT_COL,
        WIKI_PAGE_REVISIONS_COL,
        WIKI_LINKS_COL,
        WIKI_RELATIONS_COL,
        WIKI_ASSETS_COL,
        WIKI_TEMPLATES_COL,
    )
    for name in names:
        _ensure_collection_with_validator(db, name)

    db[WIKI_CATEGORIES_COL].create_index([("key", ASCENDING)], unique=True, name="ux_wiki_category_key")
    db[WIKI_CATEGORIES_COL].create_index([("slug", ASCENDING)], unique=True, name="ux_wiki_category_slug")
    db[WIKI_CATEGORIES_COL].create_index([("sort_order", ASCENDING)], name="ix_wiki_category_sort")

    db[WIKI_PAGES_COL].create_index([("slug", ASCENDING)], unique=True, name="ux_wiki_page_slug")
    db[WIKI_PAGES_COL].create_index([("category_id", ASCENDING), ("updated_at", DESCENDING)], name="ix_wiki_page_category_updated")
    db[WIKI_PAGES_COL].create_index([("entity_type", ASCENDING), ("updated_at", DESCENDING)], name="ix_wiki_page_entity_updated")
    db[WIKI_PAGES_COL].create_index([("template_id", ASCENDING)], name="ix_wiki_page_template")
    db[WIKI_PAGES_COL].create_index([("updated_at", DESCENDING)], name="ix_wiki_page_updated")
    db[WIKI_PAGES_COL].create_index(
        [("title", "text"), ("summary", "text"), ("tags", "text")],
        name="tx_wiki_page_search",
        default_language="none",
    )

    db[WIKI_PAGE_CONTENT_COL].create_index([("page_id", ASCENDING)], unique=True, name="ux_wiki_content_page")
    db[WIKI_PAGE_CONTENT_COL].create_index([("plain_text", "text")], name="tx_wiki_content_text", default_language="none")

    db[WIKI_PAGE_REVISIONS_COL].create_index([("id", ASCENDING)], unique=True, name="ux_wiki_revision_id")
    db[WIKI_PAGE_REVISIONS_COL].create_index([("page_id", ASCENDING), ("version", DESCENDING)], name="ix_wiki_revision_page_ver")

    db[WIKI_LINKS_COL].create_index([("id", ASCENDING)], unique=True, name="ux_wiki_link_id")
    db[WIKI_LINKS_COL].create_index(
        [("from_page_id", ASCENDING), ("to_page_id", ASCENDING), ("to_page_slug", ASCENDING), ("fragment", ASCENDING)],
        unique=True,
        name="ux_wiki_link_pair",
    )
    db[WIKI_LINKS_COL].create_index([("from_page_id", ASCENDING)], name="ix_wiki_link_from")
    db[WIKI_LINKS_COL].create_index([("to_page_id", ASCENDING)], name="ix_wiki_link_to")
    db[WIKI_LINKS_COL].create_index([("to_page_slug", ASCENDING)], name="ix_wiki_link_to_slug")

    db[WIKI_RELATIONS_COL].create_index([("id", ASCENDING)], unique=True, name="ux_wiki_relation_id")
    db[WIKI_RELATIONS_COL].create_index([("from_page_id", ASCENDING)], name="ix_wiki_relation_from")
    db[WIKI_RELATIONS_COL].create_index([("to_page_id", ASCENDING)], name="ix_wiki_relation_to")
    db[WIKI_RELATIONS_COL].create_index(
        [("from_page_id", ASCENDING), ("to_page_id", ASCENDING), ("relation_type", ASCENDING)],
        name="ix_wiki_relation_pair_type",
    )

    db[WIKI_ASSETS_COL].create_index([("asset_id", ASCENDING)], unique=True, name="ux_wiki_asset_id")
    db[WIKI_ASSETS_COL].create_index([("page_id", ASCENDING)], name="ix_wiki_asset_page")
    db[WIKI_TEMPLATES_COL].create_index([("id", ASCENDING)], unique=True, name="ux_wiki_template_id")
    db[WIKI_TEMPLATES_COL].create_index([("key", ASCENDING)], unique=True, name="ux_wiki_template_key")


class WikiMongoRepo:
    def __init__(self):
        self.db = get_db()
        self.categories = self.db[WIKI_CATEGORIES_COL]
        self.pages = self.db[WIKI_PAGES_COL]
        self.page_content = self.db[WIKI_PAGE_CONTENT_COL]
        self.page_revisions = self.db[WIKI_PAGE_REVISIONS_COL]
        self.links = self.db[WIKI_LINKS_COL]
        self.relations = self.db[WIKI_RELATIONS_COL]
        self.assets = self.db[WIKI_ASSETS_COL]
        self.templates = self.db[WIKI_TEMPLATES_COL]
        self._ensure_default_category()

    @staticmethod
    def _doc_without_mongo_id(doc: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(doc, dict):
            return {}
        out = dict(doc)
        out.pop("_id", None)
        return out

    def _ensure_default_category(self) -> None:
        now = utc_now()
        self.categories.update_one(
            {"key": "general"},
            {
                "$setOnInsert": {
                    "id": "general",
                    "key": "general",
                    "label": "General",
                    "slug": "general",
                    "icon": None,
                    "sort_order": 0,
                    "created_at": now,
                },
                "$set": {"updated_at": now},
            },
            upsert=True,
        )

    def list_categories(self) -> list[dict[str, Any]]:
        return [self._doc_without_mongo_id(row) for row in self.categories.find({}, {"_id": 0}).sort("sort_order", ASCENDING)]

    def get_category(self, category_id: str) -> dict[str, Any]:
        clean_id = str(category_id or "").strip()
        if not clean_id:
            return {}
        row = self.categories.find_one({"$or": [{"id": clean_id}, {"key": clean_id}, {"slug": clean_id}]})
        return self._doc_without_mongo_id(row)

    def create_category(
        self,
        *,
        key: str,
        label: str,
        slug: str = "",
        icon: str | None = None,
        sort_order: int = 0,
    ) -> dict[str, Any]:
        now = utc_now()
        clean_key = normalize_slug(key).replace("-", "_")
        if not clean_key:
            raise ValueError("Invalid category key")
        clean_slug = normalize_slug(slug or label or key)
        doc = {
            "id": clean_key,
            "key": clean_key,
            "label": str(label or "").strip(),
            "slug": clean_slug,
            "icon": (str(icon).strip() if icon else None),
            "sort_order": int(sort_order),
            "created_at": now,
            "updated_at": now,
        }
        self.categories.insert_one(doc)
        return self._doc_without_mongo_id(doc)

    def update_category(
        self,
        category_id: str,
        *,
        label: str | None = None,
        slug: str | None = None,
        icon: str | None = None,
        sort_order: int | None = None,
    ) -> dict[str, Any]:
        current = self.get_category(category_id)
        if not current:
            return {}
        update_doc: dict[str, Any] = {"updated_at": utc_now()}
        if label is not None:
            update_doc["label"] = str(label).strip()
        if slug is not None:
            update_doc["slug"] = normalize_slug(slug or current.get("label") or current.get("slug") or "")
        if icon is not None:
            update_doc["icon"] = str(icon).strip() if str(icon).strip() else None
        if sort_order is not None:
            update_doc["sort_order"] = int(sort_order)
        self.categories.update_one({"id": current["id"]}, {"$set": update_doc})
        return self.get_category(current["id"])

    def delete_category(self, category_id: str) -> bool:
        current = self.get_category(category_id)
        if not current:
            return False
        if current.get("id") == "general":
            return False
        self.pages.update_many({"category_id": current.get("id")}, {"$set": {"category_id": "general", "updated_at": utc_now()}})
        self.categories.delete_one({"id": current.get("id")})
        return True

    def list_templates(self) -> list[dict[str, Any]]:
        rows = list(self.templates.find({}, {"_id": 0}).sort("key", ASCENDING))
        return [self._doc_without_mongo_id(row) for row in rows]

    def get_template(self, template_id: str) -> dict[str, Any]:
        clean = str(template_id or "").strip()
        if not clean:
            return {}
        row = self.templates.find_one({"$or": [{"id": clean}, {"key": clean}]})
        return self._doc_without_mongo_id(row)

    def create_template(
        self,
        *,
        key: str,
        label: str,
        fields: dict[str, Any],
        description: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        clean_key = normalize_slug(key).replace("-", "_")
        if not clean_key:
            raise ValueError("Invalid template key")
        doc = {
            "id": clean_key,
            "key": clean_key,
            "label": str(label or "").strip(),
            "description": (str(description).strip() if description else None),
            "fields": normalize_entity_fields(fields),
            "created_at": now,
            "updated_at": now,
        }
        self.templates.insert_one(doc)
        return self._doc_without_mongo_id(doc)

    def update_template(
        self,
        template_id: str,
        *,
        label: str | None = None,
        fields: dict[str, Any] | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        current = self.get_template(template_id)
        if not current:
            return {}
        update_doc: dict[str, Any] = {"updated_at": utc_now()}
        if label is not None:
            update_doc["label"] = str(label).strip()
        if description is not None:
            update_doc["description"] = str(description).strip() if str(description).strip() else None
        if fields is not None:
            update_doc["fields"] = normalize_entity_fields(fields)
        self.templates.update_one({"id": current["id"]}, {"$set": update_doc})
        return self.get_template(current["id"])

    def delete_template(self, template_id: str) -> bool:
        current = self.get_template(template_id)
        if not current:
            return False
        self.templates.delete_one({"id": current.get("id")})
        self.pages.update_many(
            {"template_id": current.get("id")},
            {"$set": {"template_id": None, "updated_at": utc_now()}},
        )
        return True

    def _content_for_page_id(self, page_id: str) -> dict[str, Any]:
        return self._doc_without_mongo_id(self.page_content.find_one({"page_id": str(page_id or "").strip()}))

    def _merge_page_and_content(self, page: dict[str, Any] | None, content: dict[str, Any] | None = None) -> dict[str, Any]:
        page_doc = self._doc_without_mongo_id(page)
        if not page_doc:
            return {}
        content_doc = self._doc_without_mongo_id(content) if content is not None else self._content_for_page_id(page_doc.get("id", ""))
        page_doc["doc_json"] = content_doc.get("doc_json", {"type": "doc", "content": []})
        page_doc["plain_text"] = content_doc.get("plain_text", "")
        page_doc["content_version"] = content_doc.get("version", page_doc.get("version", 1))
        return page_doc

    def _page_ref_map(self, page_ids: list[str]) -> dict[str, dict[str, Any]]:
        clean_ids = [str(pid).strip() for pid in page_ids if str(pid).strip()]
        if not clean_ids:
            return {}
        rows = list(self.pages.find({"id": {"$in": clean_ids}}, {"_id": 0, "id": 1, "title": 1, "slug": 1, "status": 1}))
        return {
            str(row.get("id")): {
                "id": str(row.get("id") or ""),
                "title": str(row.get("title") or ""),
                "slug": str(row.get("slug") or ""),
                "status": str(row.get("status") or ""),
            }
            for row in rows
        }

    def slug_exists(self, slug: str, exclude_id: str = "") -> bool:
        query: dict[str, Any] = {"slug": str(slug or "").strip()}
        clean_exclude = str(exclude_id or "").strip()
        if clean_exclude:
            query["id"] = {"$ne": clean_exclude}
        return self.pages.find_one(query, {"_id": 1}) is not None

    def get_page_by_id(self, page_id: str) -> dict[str, Any]:
        page = self.pages.find_one({"id": str(page_id or "").strip()})
        if not page:
            return {}
        return self._merge_page_and_content(page)

    def get_page_by_slug(self, slug: str) -> dict[str, Any]:
        page = self.pages.find_one({"slug": str(slug or "").strip()})
        if not page:
            return {}
        return self._merge_page_and_content(page)

    def create_page(
        self,
        *,
        title: str,
        slug: str,
        doc_json: Any,
        created_by: str | None = None,
        category_id: str = "general",
        entity_type: str | None = None,
        template_id: str | None = None,
        fields: dict[str, Any] | None = None,
        summary: str | None = None,
        tags: list[str] | None = None,
        status: str = "draft",
        acl_override: bool = False,
        acl: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        page_id = str(uuid4())
        acl_doc = normalize_acl(acl)
        normalized_template_id = str(template_id).strip() if template_id else None
        normalized_fields = normalize_entity_fields(fields)
        if normalized_template_id and not normalized_fields:
            tpl = self.get_template(normalized_template_id)
            if tpl and isinstance(tpl.get("fields"), dict):
                normalized_fields = normalize_entity_fields(tpl.get("fields"))
        page_doc = {
            "id": page_id,
            "title": str(title or "").strip(),
            "slug": str(slug or "").strip(),
            "category_id": normalize_category_id(category_id, default="general"),
            "entity_type": normalize_entity_type(entity_type),
            "template_id": normalized_template_id,
            "fields": normalized_fields,
            "summary": normalize_summary(summary),
            "tags": normalize_tags(tags),
            "status": normalize_status(status),
            "created_by": (str(created_by).strip() if created_by else None),
            "updated_by": (str(created_by).strip() if created_by else None),
            "version": 1,
            "acl_override": bool(acl_override),
            "acl": {"view_roles": list(acl_doc["view_roles"]), "edit_roles": list(acl_doc["edit_roles"])},
            "created_at": now,
            "updated_at": now,
        }
        content_doc = {
            "page_id": page_id,
            "doc_json": doc_json,
            "plain_text": plain_text_from_doc(doc_json),
            "toc_snapshot": [],
            "version": 1,
            "updated_at": now,
        }
        self.pages.insert_one(page_doc)
        self.page_content.replace_one({"page_id": page_id}, content_doc, upsert=True)
        self.rebuild_links_for_page(page_id)
        return self._merge_page_and_content(page_doc, content_doc)

    def update_page(
        self,
        *,
        page_id: str,
        title: str,
        slug: str,
        doc_json: Any,
        category_id: str | None = None,
        entity_type: str | None = None,
        template_id: str | None = None,
        fields: dict[str, Any] | None = None,
        summary: str | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        clean_id = str(page_id or "").strip()
        existing = self.get_page_by_id(clean_id)
        if not existing:
            return {}
        now = utc_now()
        current_version = int(existing.get("version") or 1)
        next_version = current_version + 1
        self.pages.update_one(
            {"id": clean_id},
            {
                "$set": {
                    "title": str(title or "").strip(),
                    "slug": str(slug or "").strip(),
                    "category_id": normalize_category_id(category_id or existing.get("category_id") or "general"),
                    "entity_type": normalize_entity_type(entity_type if entity_type is not None else existing.get("entity_type")),
                    "template_id": (str(template_id).strip() if template_id is not None else existing.get("template_id")),
                    "fields": normalize_entity_fields(fields if fields is not None else existing.get("fields")),
                    "summary": normalize_summary(summary if summary is not None else existing.get("summary")),
                    "tags": normalize_tags(tags if tags is not None else existing.get("tags")),
                    "status": normalize_status(status if status is not None else existing.get("status", "draft")),
                    "updated_by": (str(updated_by).strip() if updated_by else None),
                    "updated_at": now,
                    "version": next_version,
                }
            },
        )
        content_doc = {
            "page_id": clean_id,
            "doc_json": doc_json,
            "plain_text": plain_text_from_doc(doc_json),
            "toc_snapshot": [],
            "version": next_version,
            "updated_at": now,
        }
        self.page_content.replace_one({"page_id": clean_id}, content_doc, upsert=True)
        self.rebuild_links_for_page(clean_id)
        return self.get_page_by_id(clean_id)

    def set_page_acl(self, *, page_id: str, acl_override: bool, acl: dict[str, Any] | None) -> dict[str, Any]:
        clean_id = str(page_id or "").strip()
        existing = self.get_page_by_id(clean_id)
        if not existing:
            return {}
        acl_doc = normalize_acl(acl)
        self.pages.update_one(
            {"id": clean_id},
            {
                "$set": {
                    "acl_override": bool(acl_override),
                    "acl": {"view_roles": list(acl_doc["view_roles"]), "edit_roles": list(acl_doc["edit_roles"])},
                    "updated_at": utc_now(),
                }
            },
        )
        return self.get_page_by_id(clean_id)

    def patch_page_fields(self, *, page_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        clean_id = str(page_id or "").strip()
        existing = self.get_page_by_id(clean_id)
        if not existing:
            return {}
        current_fields = normalize_entity_fields(existing.get("fields"))
        patch_fields = normalize_entity_fields(fields)
        current_fields.update(patch_fields)
        self.pages.update_one(
            {"id": clean_id},
            {"$set": {"fields": current_fields, "updated_at": utc_now()}},
        )
        return self.get_page_by_id(clean_id)

    def restore_revision(self, *, page_id: str, revision_id: str, restored_by: str | None = None) -> dict[str, Any]:
        clean_page_id = str(page_id or "").strip()
        revision = self.page_revisions.find_one(
            {"id": str(revision_id or "").strip(), "page_id": clean_page_id},
            {"_id": 0},
        )
        if not revision:
            return {}
        existing = self.get_page_by_id(clean_page_id)
        if not existing:
            return {}
        return self.update_page(
            page_id=clean_page_id,
            title=str(revision.get("title") or existing.get("title") or ""),
            slug=str(revision.get("slug") or existing.get("slug") or ""),
            doc_json=revision.get("doc_json") or {"type": "doc", "content": []},
            category_id=existing.get("category_id"),
            entity_type=existing.get("entity_type"),
            template_id=existing.get("template_id"),
            fields=existing.get("fields"),
            summary=existing.get("summary"),
            tags=existing.get("tags"),
            status=existing.get("status"),
            updated_by=restored_by,
        )

    def delete_page(self, page_id: str) -> bool:
        clean_id = str(page_id or "").strip()
        if not clean_id:
            return False
        deleted = self.pages.delete_one({"id": clean_id})
        if not deleted.deleted_count:
            return False
        self.page_content.delete_many({"page_id": clean_id})
        self.page_revisions.delete_many({"page_id": clean_id})
        self.links.delete_many({"$or": [{"from_page_id": clean_id}, {"to_page_id": clean_id}]})
        self.relations.delete_many({"$or": [{"from_page_id": clean_id}, {"to_page_id": clean_id}]})
        return True

    def list_pages(
        self,
        *,
        role: str,
        query: str | None = None,
        category_id: str | None = None,
        entity_type: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        acl_filter = build_page_view_filter(role)
        base_filter: dict[str, Any] = dict(acl_filter)
        and_filters: list[dict[str, Any]] = []
        if category_id:
            and_filters.append({"category_id": str(category_id).strip()})
        if entity_type:
            and_filters.append({"entity_type": normalize_entity_type(entity_type)})
        if status:
            and_filters.append({"status": normalize_status(status)})
        if tag:
            and_filters.append({"tags": {"$in": [str(tag).strip()]}})
        if query:
            pattern = re.escape(str(query or "").strip())
            rx = {"$regex": pattern, "$options": "i"}
            and_filters.append({"$or": [{"title": rx}, {"slug": rx}]})
        if and_filters:
            base_filter = {"$and": and_filters + [acl_filter]}

        total = int(self.pages.count_documents(base_filter))
        rows = list(
            self.pages.find(base_filter, {"_id": 0})
            .sort("updated_at", DESCENDING)
            .skip(int(offset))
            .limit(int(limit))
        )
        if not rows:
            return [], total
        page_ids = [str(row.get("id") or "").strip() for row in rows if str(row.get("id") or "").strip()]
        content_map = {
            str(doc.get("page_id")): self._doc_without_mongo_id(doc)
            for doc in self.page_content.find({"page_id": {"$in": page_ids}}, {"_id": 0})
        }
        merged = [self._merge_page_and_content(row, content_map.get(str(row.get("id")))) for row in rows]
        return merged, total

    def resolve_pages(self, *, role: str, query: str, limit: int = 10) -> list[dict[str, str]]:
        clean = str(query or "").strip()
        if not clean:
            return []
        acl_filter = build_page_view_filter(role)
        pattern = re.escape(clean)
        rx = {"$regex": pattern, "$options": "i"}
        rows = list(
            self.pages.find(
                {"$and": [{"$or": [{"title": rx}, {"slug": rx}]}, acl_filter]},
                {"_id": 0, "id": 1, "title": 1, "slug": 1, "updated_at": 1},
            )
            .sort("updated_at", DESCENDING)
            .limit(int(limit))
        )
        return [{"id": str(row.get("id")), "title": str(row.get("title") or ""), "slug": str(row.get("slug") or "")} for row in rows]

    def rebuild_links_for_page(self, page_id: str) -> int:
        page = self.get_page_by_id(page_id)
        if not page:
            return 0
        clean_page_id = str(page.get("id") or "").strip()
        doc_json = page.get("doc_json") or {"type": "doc", "content": []}
        extracted = extract_internal_links(doc_json, clean_page_id)
        for row in extracted:
            if not row.get("to_page_id") and row.get("to_page_slug"):
                target = self.pages.find_one({"slug": str(row.get("to_page_slug") or "").strip()}, {"_id": 0, "id": 1})
                if target:
                    row["to_page_id"] = str(target.get("id") or "").strip() or None
        self.links.delete_many({"from_page_id": clean_page_id})
        if extracted:
            self.links.insert_many(extracted)
        return len(extracted)

    def list_page_links(self, page_id: str) -> list[dict[str, Any]]:
        rows = [self._doc_without_mongo_id(row) for row in self.links.find({"from_page_id": str(page_id or "").strip()}, {"_id": 0}).sort("created_at", DESCENDING)]
        ids: list[str] = []
        for row in rows:
            ids.append(str(row.get("from_page_id") or ""))
            ids.append(str(row.get("to_page_id") or ""))
        refs = self._page_ref_map(ids)
        for row in rows:
            from_ref = refs.get(str(row.get("from_page_id") or ""))
            if from_ref:
                row["from_page"] = from_ref
            to_ref = refs.get(str(row.get("to_page_id") or ""))
            if to_ref:
                row["to_page"] = to_ref
        return rows

    def list_backlinks(self, page_id: str) -> list[dict[str, Any]]:
        clean_page_id = str(page_id or "").strip()
        page = self.get_page_by_id(clean_page_id)
        if not page:
            return []
        clean_slug = str(page.get("slug") or "").strip()
        query = {"$or": [{"to_page_id": clean_page_id}, {"to_page_slug": clean_slug}]}
        rows = [self._doc_without_mongo_id(row) for row in self.links.find(query, {"_id": 0}).sort("created_at", DESCENDING)]
        ids: list[str] = []
        for row in rows:
            ids.append(str(row.get("from_page_id") or ""))
            ids.append(str(row.get("to_page_id") or ""))
        refs = self._page_ref_map(ids)
        for row in rows:
            from_ref = refs.get(str(row.get("from_page_id") or ""))
            if from_ref:
                row["from_page"] = from_ref
            to_ref = refs.get(str(row.get("to_page_id") or ""))
            if to_ref:
                row["to_page"] = to_ref
        return rows

    def create_relation(
        self,
        *,
        from_page_id: str,
        to_page_id: str,
        relation_type: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        row = {
            "id": str(uuid4()),
            "from_page_id": str(from_page_id or "").strip(),
            "to_page_id": str(to_page_id or "").strip(),
            "relation_type": str(relation_type or "").strip().lower(),
            "note": (str(note).strip() if note else None),
            "created_at": utc_now(),
        }
        self.relations.insert_one(row)
        return self._doc_without_mongo_id(row)

    def list_relations(self, *, page_id: str) -> list[dict[str, Any]]:
        clean = str(page_id or "").strip()
        rows = list(
            self.relations.find({"$or": [{"from_page_id": clean}, {"to_page_id": clean}]}, {"_id": 0}).sort("created_at", DESCENDING)
        )
        clean_rows = [self._doc_without_mongo_id(row) for row in rows]
        ids: list[str] = []
        for row in clean_rows:
            ids.append(str(row.get("from_page_id") or ""))
            ids.append(str(row.get("to_page_id") or ""))
        refs = self._page_ref_map(ids)
        for row in clean_rows:
            from_ref = refs.get(str(row.get("from_page_id") or ""))
            if from_ref:
                row["from_page"] = from_ref
            to_ref = refs.get(str(row.get("to_page_id") or ""))
            if to_ref:
                row["to_page"] = to_ref
        return clean_rows

    def delete_relation(self, relation_id: str) -> bool:
        result = self.relations.delete_one({"id": str(relation_id or "").strip()})
        return bool(result.deleted_count)

    def page_context(self, page_id: str) -> dict[str, Any]:
        page = self.get_page_by_id(page_id)
        if not page:
            return {}
        clean_id = str(page.get("id") or "").strip()
        return {
            "page": page,
            "links": self.list_page_links(clean_id),
            "backlinks": self.list_backlinks(clean_id),
            "relations": self.list_relations(page_id=clean_id),
            "revisions": self.list_revisions(page_id=clean_id),
        }

    def create_revision(self, *, page_id: str, saved_by: str | None = None) -> dict[str, Any]:
        page = self.get_page_by_id(page_id)
        if not page:
            return {}
        revision = {
            "id": str(uuid4()),
            "page_id": str(page.get("id") or ""),
            "version": int(page.get("version") or 1),
            "doc_json": page.get("doc_json") or {"type": "doc", "content": []},
            "title": str(page.get("title") or ""),
            "slug": str(page.get("slug") or ""),
            "saved_by": (str(saved_by).strip() if saved_by else None),
            "saved_at": utc_now(),
        }
        self.page_revisions.insert_one(revision)
        return self._doc_without_mongo_id(revision)

    def list_revisions(self, *, page_id: str) -> list[dict[str, Any]]:
        rows = list(
            self.page_revisions.find({"page_id": str(page_id or "").strip()}, {"_id": 0}).sort("saved_at", DESCENDING)
        )
        return [self._doc_without_mongo_id(row) for row in rows]
