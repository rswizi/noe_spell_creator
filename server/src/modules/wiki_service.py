from __future__ import annotations

import json
import re
from datetime import datetime
from uuid import uuid4
from typing import Any

from fastapi import HTTPException

from server.src.modules.wiki_config import WIKI_ROLES, get_wiki_settings


SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WIKI_ROLE_RANK = {"viewer": 1, "editor": 2, "admin": 3}
APP_TO_WIKI_ROLE = {"user": "viewer", "moderator": "editor", "admin": "admin"}
WIKI_PAGE_STATUSES = ("draft", "published", "archived")


def utc_now() -> datetime:
    return datetime.utcnow()


def iso_utc(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def normalize_slug(value: str) -> str:
    slug = (value or "").strip().lower()
    if not slug:
        return ""
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug


def validate_slug(value: str) -> str:
    slug = normalize_slug(value)
    if not slug or not SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="Invalid slug")
    return slug


def resolve_slug(raw_slug: str, title: str) -> str:
    return validate_slug(raw_slug or title)


def normalize_status(value: Any) -> str:
    raw = str(value or "draft").strip().lower()
    if raw not in WIKI_PAGE_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid page status")
    return raw


def normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        source = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        source = [str(part).strip() for part in value]
    else:
        raise HTTPException(status_code=400, detail="tags must be a list of strings")
    tags: list[str] = []
    seen: set[str] = set()
    for raw in source:
        if not raw:
            continue
        clean = re.sub(r"\s+", " ", raw).strip()
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        tags.append(clean[:64])
    return tags[:40]


def normalize_summary(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip()
    return raw[:400] if raw else None


def normalize_category_id(value: Any, default: str = "general") -> str:
    raw = str(value or "").strip()
    return raw or default


def normalize_entity_type(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value).strip().lower()
    if not raw:
        return None
    clean = re.sub(r"[^a-z0-9_]+", "_", raw)
    clean = re.sub(r"_+", "_", clean).strip("_")
    return clean[:64] if clean else None


def sanitize_doc(doc: Any) -> Any:
    if not isinstance(doc, (dict, list)):
        raise HTTPException(status_code=400, detail="doc_json must be a JSON object or array")
    payload = json.dumps(doc, ensure_ascii=False)
    if len(payload.encode("utf-8")) > get_wiki_settings().max_doc_bytes:
        raise HTTPException(status_code=400, detail="doc_json is too large")
    return doc


def _collect_text(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        text = node.get("text")
        if isinstance(text, str) and text.strip():
            out.append(text.strip())
        content = node.get("content")
        if isinstance(content, list):
            for child in content:
                _collect_text(child, out)
    elif isinstance(node, list):
        for child in node:
            _collect_text(child, out)


def plain_text_from_doc(doc: Any) -> str:
    out: list[str] = []
    _collect_text(doc, out)
    return " ".join(out).strip()


def _sanitize_field_value(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return None
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value[:800]
    if isinstance(value, list):
        return [_sanitize_field_value(item, depth + 1) for item in value][:100]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, val in list(value.items())[:120]:
            clean_key = str(key).strip()
            if not clean_key:
                continue
            out[clean_key[:64]] = _sanitize_field_value(val, depth + 1)
        return out
    return str(value)[:800]


def normalize_entity_fields(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="fields must be an object")
    clean: dict[str, Any] = {}
    for key, val in list(value.items())[:120]:
        skey = str(key).strip()
        if not skey:
            continue
        clean[skey[:64]] = _sanitize_field_value(val, 0)
    return clean


def _visit_nodes(node: Any, visitor) -> None:
    if isinstance(node, dict):
        visitor(node)
        content = node.get("content")
        if isinstance(content, list):
            for child in content:
                _visit_nodes(child, visitor)
    elif isinstance(node, list):
        for child in node:
            _visit_nodes(child, visitor)


def extract_internal_links(doc: Any, from_page_id: str) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    clean_from = str(from_page_id or "").strip()
    if not clean_from:
        return links

    def visit(node: dict[str, Any]) -> None:
        marks = node.get("marks")
        text = str(node.get("text") or "").strip() or None
        if not isinstance(marks, list):
            return
        for mark in marks:
            if not isinstance(mark, dict) or mark.get("type") != "link":
                continue
            attrs = mark.get("attrs") or {}
            if not isinstance(attrs, dict):
                continue
            target_id = str(attrs.get("pageId") or attrs.get("page_id") or "").strip()
            target_slug = str(attrs.get("pageSlug") or attrs.get("page_slug") or "").strip()
            fragment = str(attrs.get("fragment") or "").strip() or None
            if not target_id and not target_slug:
                continue
            signature = (target_id, target_slug, fragment or "")
            if signature in seen:
                continue
            seen.add(signature)
            links.append(
                {
                    "id": str(uuid4()),
                    "from_page_id": clean_from,
                    "to_page_id": target_id or None,
                    "to_page_slug": target_slug or None,
                    "fragment": fragment,
                    "text": text,
                    "created_at": utc_now(),
                }
            )

    _visit_nodes(doc, visit)
    return links


def normalize_wiki_role(value: Any) -> str:
    role = str(value or "").strip().lower()
    return role if role in WIKI_ROLES else "viewer"


def role_at_least(role: str, minimum: str) -> bool:
    current = WIKI_ROLE_RANK.get(normalize_wiki_role(role), 1)
    needed = WIKI_ROLE_RANK.get(normalize_wiki_role(minimum), 1)
    return current >= needed


def resolve_wiki_role(app_role: str, user_doc: dict[str, Any] | None = None) -> str:
    mapped = APP_TO_WIKI_ROLE.get(str(app_role or "").strip().lower(), "viewer")
    if isinstance(user_doc, dict):
        override = str(user_doc.get("wiki_role") or "").strip().lower()
        if override in WIKI_ROLES:
            return override
    return mapped


def normalize_acl(acl: Any) -> dict[str, tuple[str, ...]]:
    cfg = get_wiki_settings()
    if not isinstance(acl, dict):
        return {
            "view_roles": tuple(cfg.default_view_roles),
            "edit_roles": tuple(cfg.default_edit_roles),
        }
    raw_view = acl.get("view_roles")
    raw_edit = acl.get("edit_roles")
    view_roles = tuple(
        role
        for role in [str(v).strip().lower() for v in (raw_view or [])]
        if role in WIKI_ROLES
    )
    edit_roles = tuple(
        role
        for role in [str(v).strip().lower() for v in (raw_edit or [])]
        if role in WIKI_ROLES
    )
    return {
        "view_roles": view_roles or tuple(cfg.default_view_roles),
        "edit_roles": edit_roles or tuple(cfg.default_edit_roles),
    }


def resolve_page_acl(page_doc: dict[str, Any] | None) -> dict[str, tuple[str, ...]]:
    cfg = get_wiki_settings()
    if not isinstance(page_doc, dict):
        return {
            "view_roles": tuple(cfg.default_view_roles),
            "edit_roles": tuple(cfg.default_edit_roles),
        }
    if not bool(page_doc.get("acl_override")):
        return {
            "view_roles": tuple(cfg.default_view_roles),
            "edit_roles": tuple(cfg.default_edit_roles),
        }
    return normalize_acl(page_doc.get("acl"))


def can_view_page(role: str, page_doc: dict[str, Any] | None) -> bool:
    if not isinstance(page_doc, dict):
        return False
    clean_role = normalize_wiki_role(role)
    status = str(page_doc.get("status") or "draft").strip().lower()
    if clean_role == "viewer" and status != "published":
        return False
    acl = resolve_page_acl(page_doc)
    return clean_role in acl["view_roles"]


def can_edit_page(
    role: str,
    page_doc: dict[str, Any] | None,
    *,
    username: str | None = None,
    editor_access_mode: str = "all",
) -> bool:
    if not isinstance(page_doc, dict):
        return False
    clean_role = normalize_wiki_role(role)
    if clean_role == "admin":
        return True
    clean_username = str(username or "").strip().lower()
    page_editors = {
        str(item).strip().lower()
        for item in (page_doc.get("editor_usernames") or [])
        if str(item).strip()
    }
    if clean_username and clean_username in page_editors:
        return True
    acl = resolve_page_acl(page_doc)
    acl_allows = clean_role in acl["edit_roles"]
    if clean_role != "editor":
        return acl_allows
    mode = str(editor_access_mode or "all").strip().lower()
    if mode != "own":
        return acl_allows
    page_owner = str(page_doc.get("created_by") or "").strip().lower()
    return bool(clean_username) and clean_username == page_owner


def build_page_view_filter(role: str) -> dict[str, Any]:
    cfg = get_wiki_settings()
    clean_role = normalize_wiki_role(role)
    filters: list[dict[str, Any]] = []
    if clean_role in cfg.default_view_roles:
        filters.append({"$or": [{"acl_override": {"$ne": True}}, {"acl_override": {"$exists": False}}]})
        filters.append(
            {
                "acl_override": True,
                "$or": [
                    {"acl.view_roles": clean_role},
                    {"acl.view_roles": {"$exists": False}},
                ],
            }
        )
    else:
        filters.append({"acl_override": True, "acl.view_roles": clean_role})
    acl_filter = {"$or": filters}
    if clean_role == "viewer":
        return {"$and": [{"status": "published"}, acl_filter]}
    return acl_filter
