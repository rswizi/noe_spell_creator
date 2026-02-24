import json
import os
import re
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from server.src.modules.wiki_auth import require_wiki_admin
from server.src.modules.wiki_db import WikiPage, WikiRevision, get_session
MAX_DOC_BYTES = int(os.environ.get("WIKI_MAX_DOC_BYTES", "200000"))
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/api/wiki",
    tags=["wiki"],
)


class WikiPagePayload(BaseModel):
    title: str
    slug: str
    doc_json: Any


class WikiPageOut(BaseModel):
    id: str
    slug: str
    title: str
    doc_json: Any
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


def sanitize_doc(doc: Any) -> Any:
    if not isinstance(doc, (dict, list)):
        raise HTTPException(status_code=400, detail="doc_json must be a JSON object or array")
    payload = json.dumps(doc, ensure_ascii=False)
    if len(payload.encode("utf-8")) > MAX_DOC_BYTES:
        raise HTTPException(status_code=400, detail="doc_json is too large")
    return doc


def _normalize_slug(value: str) -> str:
    slug = (value or "").strip().lower()
    if not slug:
        return ""
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug


def validate_slug(value: str) -> str:
    slug = _normalize_slug(value)
    if not slug or not SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="Invalid slug")
    return slug


def resolve_slug(raw_slug: str, title: str) -> str:
    return validate_slug(raw_slug or title)


def _wiki_db_error_detail(exc: Exception, operation: str) -> str:
    raw = str(getattr(exc, "orig", exc) or "")
    msg = raw.lower()
    if ("wiki_pages" in msg and "does not exist" in msg) or ("no such table" in msg and "wiki_pages" in msg):
        return "Wiki tables are missing. Run database migrations (alembic upgrade head)."
    if "permission denied" in msg:
        return "Wiki database permission error."
    if "read-only" in msg or "readonly" in msg:
        return "Wiki database is read-only."
    if "uuid" in msg and ("character varying" in msg or "varchar" in msg):
        return "Wiki ID type mismatch (UUID vs text)."
    return f"Wiki database error during {operation}."


def _page_to_dict(page: WikiPage) -> WikiPageOut:
    return WikiPageOut(
        id=str(page.id),
        slug=page.slug,
        title=page.title,
        doc_json=page.doc_json,
        created_at=page.created_at.isoformat() if page.created_at else "",
        updated_at=page.updated_at.isoformat() if page.updated_at else "",
    )


def _revision_to_dict(revision: WikiRevision) -> WikiRevisionOut:
    return WikiRevisionOut(
        id=str(revision.id),
        page_id=str(revision.page_id),
        title=revision.title,
        slug=revision.slug,
        doc_json=revision.doc_json,
        created_at=revision.created_at.isoformat(),
    )


@router.post("/pages", response_model=WikiPageOut)
async def create_page(
    payload: WikiPagePayload,
    session: AsyncSession = Depends(get_session),
    _auth: dict = Depends(require_wiki_admin),
):
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    slug = resolve_slug(payload.slug, title)
    doc_json = sanitize_doc(payload.doc_json)

    existing = await session.execute(select(WikiPage).where(WikiPage.slug == slug))
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail="Slug already exists")

    page = WikiPage(slug=slug, title=title, doc_json=doc_json)
    session.add(page)
    try:
        await session.commit()
        await session.refresh(page)
        return _page_to_dict(page)
    except IntegrityError as exc:
        await session.rollback()
        msg = str(getattr(exc, "orig", exc)).lower()
        if "slug" in msg and ("unique" in msg or "duplicate" in msg):
            raise HTTPException(status_code=409, detail="Slug already exists")
        logger.exception("wiki create_page integrity failure")
        raise HTTPException(status_code=500, detail="Wiki storage integrity error")
    except SQLAlchemyError as exc:
        await session.rollback()
        logger.exception("wiki create_page database failure")
        raise HTTPException(status_code=500, detail=_wiki_db_error_detail(exc, "page creation"))


@router.get("/pages/{page_id}", response_model=WikiPageOut)
async def get_page(page_id: str, session: AsyncSession = Depends(get_session)):
    page = await session.get(WikiPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return _page_to_dict(page)


@router.put("/pages/{page_id}", response_model=WikiPageOut)
async def update_page(
    page_id: str,
    payload: WikiPagePayload,
    session: AsyncSession = Depends(get_session),
    _auth: dict = Depends(require_wiki_admin),
):
    page = await session.get(WikiPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    slug = resolve_slug(payload.slug, title)
    doc_json = sanitize_doc(payload.doc_json)

    existing = await session.execute(
        select(WikiPage).where(WikiPage.slug == slug, WikiPage.id != page.id)
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail="Slug already exists")

    page.slug = slug
    page.title = title
    page.doc_json = doc_json
    page.updated_at = datetime.utcnow()
    try:
        await session.commit()
        await session.refresh(page)
        return _page_to_dict(page)
    except IntegrityError as exc:
        await session.rollback()
        msg = str(getattr(exc, "orig", exc)).lower()
        if "slug" in msg and ("unique" in msg or "duplicate" in msg):
            raise HTTPException(status_code=409, detail="Slug already exists")
        logger.exception("wiki update_page integrity failure")
        raise HTTPException(status_code=500, detail="Wiki storage integrity error")
    except SQLAlchemyError as exc:
        await session.rollback()
        logger.exception("wiki update_page database failure")
        raise HTTPException(status_code=500, detail=_wiki_db_error_detail(exc, "page update"))


@router.get("/pages", response_model=WikiListResponse)
async def list_pages(
    query: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    filters = []
    stmt = select(WikiPage).order_by(WikiPage.updated_at.desc()).offset(offset).limit(limit)
    if query:
        pattern = f"%{query.lower()}%"
        filters.append(or_(WikiPage.title.ilike(pattern), WikiPage.slug.ilike(pattern)))
        stmt = stmt.where(filters[-1])
    result = await session.execute(stmt)
    pages = result.scalars().all()

    count_stmt = select(func.count()).select_from(WikiPage)
    if filters:
        count_stmt = count_stmt.where(filters[-1])
    total = (await session.execute(count_stmt)).scalar_one()

    return WikiListResponse(
        items=[_page_to_dict(page) for page in pages],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/pages/slug/{slug}", response_model=WikiPageOut)
async def get_page_by_slug(slug: str, session: AsyncSession = Depends(get_session)):
    normalized = validate_slug(slug)
    stmt = select(WikiPage).where(WikiPage.slug == normalized)
    page = (await session.execute(stmt)).scalars().first()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return _page_to_dict(page)


@router.get("/resolve")
async def resolve_pages(
    query: str = Query(..., min_length=1),
    limit: int = Query(default=10, ge=1),
    session: AsyncSession = Depends(get_session),
):
    safe_limit = min(limit, 25)
    pattern = f"%{query.lower()}%"
    match_title = func.lower(WikiPage.title).ilike(pattern)
    match_slug = WikiPage.slug.ilike(pattern)
    score = case(
        (match_title, 0),
        (match_slug, 1),
        else_=2,
    )
    stmt = (
        select(WikiPage.id, WikiPage.title, WikiPage.slug)
        .where(or_(match_title, match_slug))
        .order_by(score, WikiPage.updated_at.desc())
        .limit(safe_limit)
    )
    rows = await session.execute(stmt)
    result = rows.all()
    return [{"id": str(id_), "title": title, "slug": slug} for id_, title, slug in result]


@router.post("/pages/{page_id}/revisions", response_model=WikiRevisionOut)
async def create_revision(
    page_id: str,
    session: AsyncSession = Depends(get_session),
    _auth: dict = Depends(require_wiki_admin),
):
    page = await session.get(WikiPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    revision = WikiRevision(page_id=page.id, doc_json=page.doc_json, title=page.title, slug=page.slug)
    session.add(revision)
    try:
        await session.commit()
        await session.refresh(revision)
        return _revision_to_dict(revision)
    except SQLAlchemyError as exc:
        await session.rollback()
        logger.exception("wiki create_revision database failure")
        raise HTTPException(status_code=500, detail=_wiki_db_error_detail(exc, "revision creation"))


@router.get("/pages/{page_id}/revisions", response_model=list[WikiRevisionOut])
async def list_revisions(
    page_id: str,
    session: AsyncSession = Depends(get_session),
    _auth: dict = Depends(require_wiki_admin),
):
    result = await session.execute(
        select(WikiRevision)
        .where(WikiRevision.page_id == page_id)
        .order_by(WikiRevision.created_at.desc())
    )
    revisions = result.scalars().all()
    return [_revision_to_dict(rev) for rev in revisions]
