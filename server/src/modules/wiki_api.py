from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from db_mongo import get_col
from server.src.modules.wiki_auth import require_wiki_admin, require_wiki_editor, require_wiki_viewer
from server.src.modules.wiki_repo import WikiMongoRepo
from server.src.modules.wiki_service import (
    can_edit_page,
    can_view_page,
    iso_utc,
    normalize_acl,
    normalize_entity_fields,
    normalize_entity_type,
    normalize_status,
    normalize_wiki_role,
    resolve_slug,
    resolve_wiki_role,
    sanitize_doc,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/wiki", tags=["wiki"])


class WikiCategoryPayload(BaseModel):
    key: str
    label: str
    slug: str = ""
    icon: str | None = None
    parent_id: str | None = None
    sort_order: int = 0


class WikiCategoryUpdatePayload(BaseModel):
    label: str | None = None
    slug: str | None = None
    icon: str | None = None
    parent_id: str | None = None
    sort_order: int | None = None


class WikiCategoryOut(BaseModel):
    id: str
    key: str
    label: str
    slug: str
    icon: str | None = None
    parent_id: str | None = None
    sort_order: int = 0
    created_at: str
    updated_at: str


class WikiTemplatePayload(BaseModel):
    key: str
    label: str
    description: str | None = None
    fields: dict[str, Any] = {}


class WikiTemplateUpdatePayload(BaseModel):
    label: str | None = None
    description: str | None = None
    fields: dict[str, Any] | None = None


class WikiTemplateOut(BaseModel):
    id: str
    key: str
    label: str
    description: str | None = None
    fields: dict[str, Any] = {}
    created_at: str
    updated_at: str


class WikiPagePayload(BaseModel):
    title: str
    slug: str = ""
    doc_json: Any
    category_id: str | None = None
    entity_type: str | None = None
    template_id: str | None = None
    fields: dict[str, Any] | None = None
    summary: str | None = None
    tags: list[str] | None = None
    status: str | None = None


class WikiPageOut(BaseModel):
    id: str
    slug: str
    title: str
    doc_json: Any
    category_id: str
    entity_type: str | None = None
    template_id: str | None = None
    fields: dict[str, Any] = {}
    summary: str | None = None
    tags: list[str] = []
    status: str = "draft"
    acl_override: bool = False
    acl: dict[str, list[str]] | None = None
    editor_usernames: list[str] = []
    created_at: str
    updated_at: str


class WikiRevisionOut(BaseModel):
    id: str
    page_id: str
    title: str
    slug: str
    doc_json: Any
    created_at: str


class WikiListResponse(BaseModel):
    items: list[WikiPageOut]
    total: int
    limit: int
    offset: int


class WikiAclPayload(BaseModel):
    acl_override: bool = False
    view_roles: list[str] | None = None
    edit_roles: list[str] | None = None


class WikiRelationPayload(BaseModel):
    to_page_id: str
    relation_type: str
    note: str | None = None


class WikiFieldsPatchPayload(BaseModel):
    fields: dict[str, Any] = {}


class WikiPageEditorsPayload(BaseModel):
    editor_usernames: list[str] = []


class WikiSiteSettingsPayload(BaseModel):
    editor_access_mode: str


class WikiSiteSettingsOut(BaseModel):
    id: str = "site"
    editor_access_mode: str = "all"
    updated_at: str


class WikiUserRoleOut(BaseModel):
    username: str
    role: str
    wiki_role: str


class WikiUserRolePayload(BaseModel):
    wiki_role: str


def _repo() -> WikiMongoRepo:
    return WikiMongoRepo()


def _category_to_out(row: dict[str, Any]) -> WikiCategoryOut:
    return WikiCategoryOut(
        id=str(row.get("id") or ""),
        key=str(row.get("key") or ""),
        label=str(row.get("label") or ""),
        slug=str(row.get("slug") or ""),
        icon=(str(row.get("icon")) if row.get("icon") else None),
        parent_id=(str(row.get("parent_id")) if row.get("parent_id") else None),
        sort_order=int(row.get("sort_order") or 0),
        created_at=iso_utc(row.get("created_at")),
        updated_at=iso_utc(row.get("updated_at")),
    )


def _template_to_out(row: dict[str, Any]) -> WikiTemplateOut:
    return WikiTemplateOut(
        id=str(row.get("id") or ""),
        key=str(row.get("key") or ""),
        label=str(row.get("label") or ""),
        description=(str(row.get("description")) if row.get("description") is not None else None),
        fields=row.get("fields") if isinstance(row.get("fields"), dict) else {},
        created_at=iso_utc(row.get("created_at")),
        updated_at=iso_utc(row.get("updated_at")),
    )


def _page_to_out(page: dict[str, Any]) -> WikiPageOut:
    acl_raw = page.get("acl") if isinstance(page.get("acl"), dict) else {}
    view_roles = [str(v) for v in (acl_raw.get("view_roles") or []) if str(v).strip()]
    edit_roles = [str(v) for v in (acl_raw.get("edit_roles") or []) if str(v).strip()]
    return WikiPageOut(
        id=str(page.get("id") or ""),
        slug=str(page.get("slug") or ""),
        title=str(page.get("title") or ""),
        doc_json=page.get("doc_json") or {"type": "doc", "content": []},
        category_id=str(page.get("category_id") or "general"),
        entity_type=(str(page.get("entity_type")) if page.get("entity_type") is not None else None),
        template_id=(str(page.get("template_id")) if page.get("template_id") is not None else None),
        fields=page.get("fields") if isinstance(page.get("fields"), dict) else {},
        summary=(str(page.get("summary")) if page.get("summary") is not None else None),
        tags=[str(tag) for tag in (page.get("tags") or []) if str(tag).strip()],
        status=str(page.get("status") or "draft"),
        acl_override=bool(page.get("acl_override")),
        acl={"view_roles": view_roles, "edit_roles": edit_roles},
        editor_usernames=[str(item).strip().lower() for item in (page.get("editor_usernames") or []) if str(item).strip()],
        created_at=iso_utc(page.get("created_at")),
        updated_at=iso_utc(page.get("updated_at")),
    )


def _revision_to_out(revision: dict[str, Any]) -> WikiRevisionOut:
    return WikiRevisionOut(
        id=str(revision.get("id") or ""),
        page_id=str(revision.get("page_id") or ""),
        title=str(revision.get("title") or ""),
        slug=str(revision.get("slug") or ""),
        doc_json=revision.get("doc_json") or {"type": "doc", "content": []},
        created_at=iso_utc(revision.get("saved_at") or revision.get("created_at")),
    )


def _site_settings_to_out(row: dict[str, Any]) -> WikiSiteSettingsOut:
    mode = str(row.get("editor_access_mode") or "all").strip().lower()
    return WikiSiteSettingsOut(
        id="site",
        editor_access_mode=mode if mode in {"all", "own"} else "all",
        updated_at=iso_utc(row.get("updated_at")),
    )


def _clean_username_list(items: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in (items or []):
        clean = str(raw or "").strip().lower()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean[:64])
    return out


def _list_wiki_users() -> list[WikiUserRoleOut]:
    rows = list(get_col("users").find({}, {"_id": 0, "username": 1, "role": 1, "wiki_role": 1}))
    out: list[WikiUserRoleOut] = []
    for row in rows:
        username = str(row.get("username") or "").strip()
        if not username:
            continue
        app_role = str(row.get("role") or "user").strip().lower() or "user"
        wiki_role = normalize_wiki_role(resolve_wiki_role(app_role, row))
        out.append(WikiUserRoleOut(username=username, role=app_role, wiki_role=wiki_role))
    out.sort(key=lambda item: item.username.lower())
    return out


def _can_edit_with_auth(repo: WikiMongoRepo, auth: dict[str, Any], page: dict[str, Any]) -> bool:
    settings = repo.get_site_settings()
    return can_edit_page(
        str(auth.get("wiki_role") or "viewer"),
        page,
        username=str(auth.get("username") or ""),
        editor_access_mode=str(settings.get("editor_access_mode") or "all"),
    )


@router.get("/categories", response_model=list[WikiCategoryOut])
async def list_categories(auth: dict[str, Any] = Depends(require_wiki_viewer)):
    _ = auth
    try:
        return [_category_to_out(row) for row in _repo().list_categories()]
    except Exception:
        logger.exception("wiki list_categories failure")
        raise HTTPException(status_code=500, detail="Wiki database error during category listing.")


@router.post("/categories", response_model=WikiCategoryOut)
async def create_category(
    payload: WikiCategoryPayload,
    auth: dict[str, Any] = Depends(require_wiki_admin),
):
    _ = auth
    key = payload.key.strip()
    label = payload.label.strip()
    if not key or not label:
        raise HTTPException(status_code=400, detail="key and label are required")
    try:
        row = _repo().create_category(
            key=key,
            label=label,
            slug=payload.slug,
            icon=payload.icon,
            parent_id=payload.parent_id,
            sort_order=payload.sort_order,
        )
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Category key/slug already exists")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception:
        logger.exception("wiki create_category failure")
        raise HTTPException(status_code=500, detail="Wiki database error during category creation.")
    return _category_to_out(row)


@router.put("/categories/{category_id}", response_model=WikiCategoryOut)
async def update_category(
    category_id: str,
    payload: WikiCategoryUpdatePayload,
    auth: dict[str, Any] = Depends(require_wiki_admin),
):
    _ = auth
    repo = _repo()
    if not repo.get_category(category_id):
        raise HTTPException(status_code=404, detail="Category not found")
    try:
        row = repo.update_category(
            category_id,
            label=payload.label,
            slug=payload.slug,
            icon=payload.icon,
            parent_id=payload.parent_id,
            sort_order=payload.sort_order,
        )
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Category slug already exists")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("wiki update_category failure")
        raise HTTPException(status_code=500, detail="Wiki database error during category update.")
    return _category_to_out(row)


@router.delete("/categories/{category_id}")
async def delete_category(
    category_id: str,
    auth: dict[str, Any] = Depends(require_wiki_admin),
):
    _ = auth
    repo = _repo()
    ok = repo.delete_category(category_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Unable to delete category")
    return {"ok": True}


@router.get("/templates", response_model=list[WikiTemplateOut])
async def list_templates(auth: dict[str, Any] = Depends(require_wiki_viewer)):
    _ = auth
    try:
        return [_template_to_out(row) for row in _repo().list_templates()]
    except Exception:
        logger.exception("wiki list_templates failure")
        raise HTTPException(status_code=500, detail="Wiki database error during template listing.")


@router.post("/templates", response_model=WikiTemplateOut)
async def create_template(
    payload: WikiTemplatePayload,
    auth: dict[str, Any] = Depends(require_wiki_admin),
):
    _ = auth
    key = payload.key.strip()
    label = payload.label.strip()
    if not key or not label:
        raise HTTPException(status_code=400, detail="key and label are required")
    try:
        row = _repo().create_template(
            key=key,
            label=label,
            fields=normalize_entity_fields(payload.fields),
            description=payload.description,
        )
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Template key already exists")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception:
        logger.exception("wiki create_template failure")
        raise HTTPException(status_code=500, detail="Wiki database error during template creation.")
    return _template_to_out(row)


@router.put("/templates/{template_id}", response_model=WikiTemplateOut)
async def update_template(
    template_id: str,
    payload: WikiTemplateUpdatePayload,
    auth: dict[str, Any] = Depends(require_wiki_admin),
):
    _ = auth
    repo = _repo()
    if not repo.get_template(template_id):
        raise HTTPException(status_code=404, detail="Template not found")
    try:
        row = repo.update_template(
            template_id=template_id,
            label=payload.label,
            description=payload.description,
            fields=normalize_entity_fields(payload.fields) if payload.fields is not None else None,
        )
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Template conflict")
    except HTTPException:
        raise
    except Exception:
        logger.exception("wiki update_template failure")
        raise HTTPException(status_code=500, detail="Wiki database error during template update.")
    return _template_to_out(row)


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: str,
    auth: dict[str, Any] = Depends(require_wiki_admin),
):
    _ = auth
    ok = _repo().delete_template(template_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"ok": True}


@router.get("/me")
async def get_wiki_me(auth: dict[str, Any] = Depends(require_wiki_viewer)):
    return {
        "username": str(auth.get("username") or ""),
        "role": str(auth.get("role") or ""),
        "wiki_role": str(auth.get("wiki_role") or "viewer"),
    }


@router.get("/settings", response_model=WikiSiteSettingsOut)
async def get_wiki_settings_route(auth: dict[str, Any] = Depends(require_wiki_admin)):
    _ = auth
    try:
        return _site_settings_to_out(_repo().get_site_settings())
    except Exception:
        logger.exception("wiki get settings failure")
        raise HTTPException(status_code=500, detail="Wiki database error during settings load.")


@router.put("/settings", response_model=WikiSiteSettingsOut)
async def update_wiki_settings_route(
    payload: WikiSiteSettingsPayload,
    auth: dict[str, Any] = Depends(require_wiki_admin),
):
    _ = auth
    try:
        row = _repo().update_site_settings(editor_access_mode=payload.editor_access_mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("wiki update settings failure")
        raise HTTPException(status_code=500, detail="Wiki database error during settings update.")
    return _site_settings_to_out(row)


@router.get("/users", response_model=list[WikiUserRoleOut])
async def list_wiki_users(auth: dict[str, Any] = Depends(require_wiki_admin)):
    _ = auth
    try:
        return _list_wiki_users()
    except Exception:
        logger.exception("wiki list users failure")
        raise HTTPException(status_code=500, detail="Wiki database error during user listing.")


@router.put("/users/{username}/role", response_model=WikiUserRoleOut)
async def update_wiki_user_role(
    username: str,
    payload: WikiUserRolePayload,
    auth: dict[str, Any] = Depends(require_wiki_admin),
):
    _ = auth
    clean_username = str(username or "").strip()
    if not clean_username:
        raise HTTPException(status_code=400, detail="username is required")
    clean_wiki_role = str(payload.wiki_role or "").strip().lower()
    if clean_wiki_role not in {"viewer", "editor", "admin"}:
        raise HTTPException(status_code=400, detail="Invalid wiki_role")
    try:
        users = get_col("users")
        current = users.find_one({"username": clean_username}, {"_id": 0, "username": 1, "role": 1, "wiki_role": 1})
        if not current:
            raise HTTPException(status_code=404, detail="User not found")
        users.update_one({"username": clean_username}, {"$set": {"wiki_role": clean_wiki_role}})
        updated = users.find_one({"username": clean_username}, {"_id": 0, "username": 1, "role": 1, "wiki_role": 1}) or {}
    except HTTPException:
        raise
    except Exception:
        logger.exception("wiki update user role failure")
        raise HTTPException(status_code=500, detail="Wiki database error during user role update.")
    app_role = str(updated.get("role") or "user").strip().lower() or "user"
    effective_wiki_role = normalize_wiki_role(resolve_wiki_role(app_role, updated))
    return WikiUserRoleOut(username=clean_username, role=app_role, wiki_role=effective_wiki_role)


@router.post("/pages", response_model=WikiPageOut)
async def create_page(
    payload: WikiPagePayload,
    auth: dict[str, Any] = Depends(require_wiki_editor),
):
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    slug = resolve_slug(payload.slug, title)
    doc_json = sanitize_doc(payload.doc_json)
    repo = _repo()
    if repo.slug_exists(slug):
        raise HTTPException(status_code=409, detail="Slug already exists")
    try:
        page = repo.create_page(
            title=title,
            slug=slug,
            doc_json=doc_json,
            category_id=payload.category_id or "general",
            entity_type=normalize_entity_type(payload.entity_type),
            template_id=(payload.template_id or None),
            fields=normalize_entity_fields(payload.fields),
            summary=payload.summary,
            tags=payload.tags,
            status=payload.status or "draft",
            created_by=str(auth.get("username") or "unknown"),
        )
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Slug already exists")
    except HTTPException:
        raise
    except Exception:
        logger.exception("wiki create_page failure")
        raise HTTPException(status_code=500, detail="Wiki database error during page creation.")
    return _page_to_out(page)


@router.get("/pages/{page_id}", response_model=WikiPageOut)
async def get_page(page_id: str, auth: dict[str, Any] = Depends(require_wiki_viewer)):
    repo = _repo()
    page = repo.get_page_by_id(page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    if not can_view_page(str(auth.get("wiki_role") or "viewer"), page):
        raise HTTPException(status_code=403, detail="Forbidden")
    return _page_to_out(page)


@router.put("/pages/{page_id}", response_model=WikiPageOut)
async def update_page(
    page_id: str,
    payload: WikiPagePayload,
    auth: dict[str, Any] = Depends(require_wiki_editor),
):
    repo = _repo()
    existing = repo.get_page_by_id(page_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Page not found")
    if not _can_edit_with_auth(repo, auth, existing):
        raise HTTPException(status_code=403, detail="Forbidden")

    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    slug = resolve_slug(payload.slug, title)
    doc_json = sanitize_doc(payload.doc_json)
    if repo.slug_exists(slug, exclude_id=page_id):
        raise HTTPException(status_code=409, detail="Slug already exists")

    try:
        page = repo.update_page(
            page_id=page_id,
            title=title,
            slug=slug,
            doc_json=doc_json,
            category_id=payload.category_id,
            entity_type=normalize_entity_type(payload.entity_type) if payload.entity_type is not None else None,
            template_id=payload.template_id if payload.template_id is not None else None,
            fields=normalize_entity_fields(payload.fields) if payload.fields is not None else None,
            summary=payload.summary,
            tags=payload.tags,
            status=payload.status,
            updated_by=str(auth.get("username") or "unknown"),
        )
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Slug already exists")
    except HTTPException:
        raise
    except Exception:
        logger.exception("wiki update_page failure")
        raise HTTPException(status_code=500, detail="Wiki database error during page update.")
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return _page_to_out(page)


@router.patch("/pages/{page_id}/fields", response_model=WikiPageOut)
async def patch_page_fields(
    page_id: str,
    payload: WikiFieldsPatchPayload,
    auth: dict[str, Any] = Depends(require_wiki_editor),
):
    repo = _repo()
    existing = repo.get_page_by_id(page_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Page not found")
    if not _can_edit_with_auth(repo, auth, existing):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        page = repo.patch_page_fields(page_id=page_id, fields=normalize_entity_fields(payload.fields))
    except HTTPException:
        raise
    except Exception:
        logger.exception("wiki patch_page_fields failure")
        raise HTTPException(status_code=500, detail="Wiki database error during fields update.")
    return _page_to_out(page)


@router.delete("/pages/{page_id}")
async def delete_page(
    page_id: str,
    auth: dict[str, Any] = Depends(require_wiki_editor),
):
    repo = _repo()
    existing = repo.get_page_by_id(page_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Page not found")
    if not _can_edit_with_auth(repo, auth, existing):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        ok = repo.delete_page(page_id)
    except Exception:
        logger.exception("wiki delete_page failure")
        raise HTTPException(status_code=500, detail="Wiki database error during page deletion.")
    if not ok:
        raise HTTPException(status_code=404, detail="Page not found")
    return {"ok": True}


@router.put("/pages/{page_id}/acl", response_model=WikiPageOut)
async def update_page_acl(
    page_id: str,
    payload: WikiAclPayload,
    auth: dict[str, Any] = Depends(require_wiki_admin),
):
    _ = auth
    repo = _repo()
    existing = repo.get_page_by_id(page_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Page not found")
    acl = normalize_acl({"view_roles": payload.view_roles, "edit_roles": payload.edit_roles})
    try:
        page = repo.set_page_acl(
            page_id=page_id,
            acl_override=bool(payload.acl_override),
            acl={"view_roles": list(acl["view_roles"]), "edit_roles": list(acl["edit_roles"])},
        )
    except Exception:
        logger.exception("wiki update_page_acl failure")
        raise HTTPException(status_code=500, detail="Wiki database error during ACL update.")
    return _page_to_out(page)


@router.put("/pages/{page_id}/editors", response_model=WikiPageOut)
async def update_page_editors(
    page_id: str,
    payload: WikiPageEditorsPayload,
    auth: dict[str, Any] = Depends(require_wiki_admin),
):
    _ = auth
    repo = _repo()
    existing = repo.get_page_by_id(page_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Page not found")
    try:
        page = repo.set_page_editors(page_id=page_id, editor_usernames=_clean_username_list(payload.editor_usernames))
    except Exception:
        logger.exception("wiki update_page_editors failure")
        raise HTTPException(status_code=500, detail="Wiki database error during editors update.")
    return _page_to_out(page)


@router.get("/pages", response_model=WikiListResponse)
async def list_pages(
    query: str | None = Query(default=None),
    category_id: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    auth: dict[str, Any] = Depends(require_wiki_viewer),
):
    if status is not None:
        _ = normalize_status(status)
    if entity_type is not None:
        entity_type = normalize_entity_type(entity_type)
    repo = _repo()
    try:
        items, total = repo.list_pages(
            role=str(auth.get("wiki_role") or "viewer"),
            query=query,
            category_id=category_id,
            entity_type=entity_type,
            status=status,
            tag=tag,
            limit=limit,
            offset=offset,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("wiki list_pages failure")
        raise HTTPException(status_code=500, detail="Wiki database error during page listing.")
    return WikiListResponse(items=[_page_to_out(page) for page in items], total=int(total), limit=limit, offset=offset)


@router.get("/pages/slug/{slug}", response_model=WikiPageOut)
async def get_page_by_slug(slug: str, auth: dict[str, Any] = Depends(require_wiki_viewer)):
    repo = _repo()
    normalized = resolve_slug(slug, slug)
    page = repo.get_page_by_slug(normalized)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    if not can_view_page(str(auth.get("wiki_role") or "viewer"), page):
        raise HTTPException(status_code=403, detail="Forbidden")
    return _page_to_out(page)


@router.get("/resolve")
async def resolve_pages(
    query: str = Query(..., min_length=1),
    limit: int = Query(default=10, ge=1),
    auth: dict[str, Any] = Depends(require_wiki_viewer),
):
    safe_limit = min(limit, 25)
    try:
        return _repo().resolve_pages(role=str(auth.get("wiki_role") or "viewer"), query=query, limit=safe_limit)
    except Exception:
        logger.exception("wiki resolve failure")
        raise HTTPException(status_code=500, detail="Wiki database error during page resolve.")


@router.post("/pages/{page_id}/links/rebuild")
async def rebuild_links(page_id: str, auth: dict[str, Any] = Depends(require_wiki_editor)):
    repo = _repo()
    page = repo.get_page_by_id(page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    if not _can_edit_with_auth(repo, auth, page):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        count = repo.rebuild_links_for_page(page_id)
    except Exception:
        logger.exception("wiki rebuild_links failure")
        raise HTTPException(status_code=500, detail="Wiki database error during link rebuild.")
    return {"ok": True, "count": int(count)}


@router.get("/pages/{page_id}/links")
async def list_links(page_id: str, auth: dict[str, Any] = Depends(require_wiki_viewer)):
    repo = _repo()
    page = repo.get_page_by_id(page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    if not can_view_page(str(auth.get("wiki_role") or "viewer"), page):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        return repo.list_page_links(page_id)
    except Exception:
        logger.exception("wiki list_links failure")
        raise HTTPException(status_code=500, detail="Wiki database error during link listing.")


@router.get("/pages/{page_id}/backlinks")
async def list_backlinks(page_id: str, auth: dict[str, Any] = Depends(require_wiki_viewer)):
    repo = _repo()
    page = repo.get_page_by_id(page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    if not can_view_page(str(auth.get("wiki_role") or "viewer"), page):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        return repo.list_backlinks(page_id)
    except Exception:
        logger.exception("wiki list_backlinks failure")
        raise HTTPException(status_code=500, detail="Wiki database error during backlink listing.")


@router.get("/pages/{page_id}/context")
async def get_page_context(page_id: str, auth: dict[str, Any] = Depends(require_wiki_viewer)):
    repo = _repo()
    page = repo.get_page_by_id(page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    if not can_view_page(str(auth.get("wiki_role") or "viewer"), page):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        context = repo.page_context(page_id)
    except Exception:
        logger.exception("wiki page_context failure")
        raise HTTPException(status_code=500, detail="Wiki database error during page context load.")
    if not context:
        raise HTTPException(status_code=404, detail="Page not found")
    page_out = _page_to_out(context.get("page", {}))
    context["page"] = page_out.model_dump() if hasattr(page_out, "model_dump") else page_out.dict()
    return context


@router.post("/pages/{page_id}/revisions", response_model=WikiRevisionOut)
async def create_revision(page_id: str, auth: dict[str, Any] = Depends(require_wiki_editor)):
    repo = _repo()
    page = repo.get_page_by_id(page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    if not _can_edit_with_auth(repo, auth, page):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        revision = repo.create_revision(page_id=page_id, saved_by=str(auth.get("username") or "unknown"))
    except Exception:
        logger.exception("wiki create_revision failure")
        raise HTTPException(status_code=500, detail="Wiki database error during revision creation.")
    return _revision_to_out(revision)


@router.get("/pages/{page_id}/revisions", response_model=list[WikiRevisionOut])
async def list_revisions(page_id: str, auth: dict[str, Any] = Depends(require_wiki_viewer)):
    repo = _repo()
    page = repo.get_page_by_id(page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    if not can_view_page(str(auth.get("wiki_role") or "viewer"), page):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        revisions = repo.list_revisions(page_id=page_id)
    except Exception:
        logger.exception("wiki list_revisions failure")
        raise HTTPException(status_code=500, detail="Wiki database error during revision listing.")
    return [_revision_to_out(revision) for revision in revisions]


@router.post("/pages/{page_id}/revisions/{revision_id}/restore", response_model=WikiPageOut)
async def restore_revision(
    page_id: str,
    revision_id: str,
    auth: dict[str, Any] = Depends(require_wiki_editor),
):
    repo = _repo()
    page = repo.get_page_by_id(page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    if not _can_edit_with_auth(repo, auth, page):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        restored = repo.restore_revision(
            page_id=page_id,
            revision_id=revision_id,
            restored_by=str(auth.get("username") or "unknown"),
        )
    except Exception:
        logger.exception("wiki restore_revision failure")
        raise HTTPException(status_code=500, detail="Wiki database error during revision restore.")
    if not restored:
        raise HTTPException(status_code=404, detail="Revision not found")
    return _page_to_out(restored)


@router.get("/pages/{page_id}/relations")
async def list_relations(page_id: str, auth: dict[str, Any] = Depends(require_wiki_viewer)):
    repo = _repo()
    page = repo.get_page_by_id(page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    if not can_view_page(str(auth.get("wiki_role") or "viewer"), page):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        return repo.list_relations(page_id=page_id)
    except Exception:
        logger.exception("wiki list_relations failure")
        raise HTTPException(status_code=500, detail="Wiki database error during relations listing.")


@router.post("/pages/{page_id}/relations")
async def create_relation(
    page_id: str,
    payload: WikiRelationPayload,
    auth: dict[str, Any] = Depends(require_wiki_editor),
):
    repo = _repo()
    source = repo.get_page_by_id(page_id)
    target = repo.get_page_by_id(payload.to_page_id)
    if not source or not target:
        raise HTTPException(status_code=404, detail="Page not found")
    if not _can_edit_with_auth(repo, auth, source):
        raise HTTPException(status_code=403, detail="Forbidden")
    rel_type = str(payload.relation_type or "").strip().lower()
    if not rel_type:
        raise HTTPException(status_code=400, detail="relation_type is required")
    try:
        return repo.create_relation(
            from_page_id=page_id,
            to_page_id=payload.to_page_id,
            relation_type=rel_type,
            note=payload.note,
        )
    except Exception:
        logger.exception("wiki create_relation failure")
        raise HTTPException(status_code=500, detail="Wiki database error during relation creation.")


@router.delete("/relations/{relation_id}")
async def delete_relation(
    relation_id: str,
    auth: dict[str, Any] = Depends(require_wiki_editor),
):
    _ = auth
    try:
        ok = _repo().delete_relation(relation_id)
    except Exception:
        logger.exception("wiki delete_relation failure")
        raise HTTPException(status_code=500, detail="Wiki database error during relation deletion.")
    if not ok:
        raise HTTPException(status_code=404, detail="Relation not found")
    return {"ok": True}
