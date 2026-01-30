import json
import os
import re
import secrets
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.src.modules.authentification_helpers import get_auth_token, require_auth
from server.src.modules.wiki_db import WikiPage, WikiRevision, get_session

API_TOKEN = os.environ.get("API_TOKEN", "")
ENV = os.environ.get("ENV", "development").lower()
if ENV == "production" and not API_TOKEN:
    raise RuntimeError("API_TOKEN must be set in production for wiki API")
elif not API_TOKEN:
    print("WARNING: Running wiki API without API_TOKEN (allowed only in non-production environments)")
MAX_DOC_BYTES = int(os.environ.get("WIKI_MAX_DOC_BYTES", "200000"))
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


async def wiki_auth(request: Request):
    try:
        username, role = require_auth(request)
        return {"username": username, "role": role}
    except HTTPException:
        token = get_auth_token(request)
        if token and API_TOKEN and secrets.compare_digest(token, API_TOKEN):
            return {"username": "api", "role": "api"}
        raise HTTPException(status_code=401, detail="Not authenticated")


router = APIRouter(
    prefix="/api/wiki",
    tags=["wiki"],
    dependencies=[Depends(wiki_auth)],
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


def validate_slug(value: str) -> str:
    slug = (value or "").strip().lower()
    if not slug or not SLUG_RE.match(slug):
        raise HTTPException(status_code=400, detail="Invalid slug")
    return slug


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
):
    slug = validate_slug(payload.slug)
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    doc_json = sanitize_doc(payload.doc_json)

    existing = await session.execute(select(WikiPage).where(WikiPage.slug == slug))
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail="Slug already exists")

    page = WikiPage(slug=slug, title=title, doc_json=doc_json)
    session.add(page)
    await session.commit()
    await session.refresh(page)
    return _page_to_dict(page)


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
):
    page = await session.get(WikiPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    slug = validate_slug(payload.slug)
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
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
    await session.commit()
    await session.refresh(page)
    return _page_to_dict(page)


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


@router.post("/pages/{page_id}/revisions", response_model=WikiRevisionOut)
async def create_revision(page_id: str, session: AsyncSession = Depends(get_session)):
    page = await session.get(WikiPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    revision = WikiRevision(page_id=page.id, doc_json=page.doc_json, title=page.title, slug=page.slug)
    session.add(revision)
    await session.commit()
    await session.refresh(revision)
    return _revision_to_dict(revision)


@router.get("/pages/{page_id}/revisions", response_model=list[WikiRevisionOut])
async def list_revisions(page_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(WikiRevision)
        .where(WikiRevision.page_id == page_id)
        .order_by(WikiRevision.created_at.desc())
    )
    revisions = result.scalars().all()
    return [_revision_to_dict(rev) for rev in revisions]
