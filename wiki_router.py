# wiki_router.py (clean + Pylance-friendly)
from __future__ import annotations

from datetime import datetime, timezone
import os
import re
from typing import Any, Dict, List, Optional, Annotated

from bson import ObjectId
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from pydantic import BaseModel, Field, StringConstraints
from pymongo import ASCENDING, DESCENDING, TEXT
from pymongo.errors import DuplicateKeyError

from db_mongo import get_col, get_db, norm_key

router = APIRouter(prefix="/wiki", tags=["wiki"])

# ------------------------------- helpers ------------------------------------ #

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _oid(value: Optional[str]) -> Optional[ObjectId]:
    if not value:
        return None
    try:
        return ObjectId(value)
    except Exception:
        return None

SLUG_RE = re.compile(r"[^a-z0-9\-]+")

def slugify(title: str) -> str:
    s = norm_key(title or "").lower().replace("_", "-")
    s = SLUG_RE.sub("-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "page"

def _plain_text_from_html(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "").strip()

def _require_admin(x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token")) -> None:
    needed = os.getenv("WIKI_ADMIN_TOKEN")
    if not needed:
        # No token configured -> allow all (useful for local dev).
        return
    if x_admin_token != needed:
        raise HTTPException(status_code=403, detail="Admin token required.")

def _pages():
    return get_col("wiki_pages")

def _revs():
    return get_col("wiki_revisions")

def _cats():
    return get_col("wiki_categories")

def _unique_slug(base: str, ignore_id: Optional[ObjectId] = None) -> str:
    slug = slugify(base) or "page"
    n = 1
    while True:
        q: Dict[str, Any] = {"slug": slug}
        if ignore_id:
            q["_id"] = {"$ne": ignore_id}
        if _pages().count_documents(q, limit=1) == 0:
            return slug
        n += 1
        slug = f"{slug}-{n}"

def _record_revision(page_id: ObjectId, data: Dict[str, Any], note: str = "") -> None:
    _revs().insert_one({
        "page_id": page_id,
        "title": data.get("title"),
        "content_html": data.get("content_html"),
        "content_markdown": data.get("content_markdown"),
        "content_format": data.get("content_format", "html"),
        "summary": data.get("summary") or "",
        "note": note or data.get("revision_note") or "",
        "tags": data.get("tags") or [],
        "category_ids": data.get("category_ids") or [],
        "created_at": now_utc(),
    })

def _page_public(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Full page payload for detail view."""
    return {
        "id": str(doc["_id"]),
        "slug": doc["slug"],
        "title": doc["title"],
        "summary": doc.get("summary", ""),
        "content_html": doc.get("content_html", ""),
        "content_markdown": doc.get("content_markdown", ""),
        "content_format": doc.get("content_format", "html"),
        "html": doc.get("content_html", ""),  # friendly alias for PortalWikiPage.jsx
        "status": doc["status"],
        "tags": doc.get("tags", []),
        "category_ids": [str(x) for x in doc.get("category_ids", [])],
        "categories": doc.get("categories", []),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "published_at": doc.get("published_at"),
        "author_id": str(doc["author_id"]) if doc.get("author_id") else None,
        "images": doc.get("images", []),
        "views": doc.get("views", 0),
        "likes": doc.get("likes", 0),
        "category_path": doc.get("category_path", []),
    }

def _page_list_item(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Lightweight serializer for listings/search."""
    excerpt = (doc.get("summary") or doc.get("plain_text") or "")[:280].rstrip()
    return {
        "id": str(doc["_id"]),
        "slug": doc["slug"],
        "title": doc["title"],
        "excerpt": excerpt,
        "status": doc["status"],
        "tags": doc.get("tags", []),
        "category_ids": [str(x) for x in doc.get("category_ids", [])],
        "category": doc.get("category"),  # optional denormalized
        "category_path": doc.get("category_path", []),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "views": doc.get("views", 0),
        "likes": doc.get("likes", 0),
    }

def _ensure_indexes() -> Dict[str, Any]:
    """Idempotent index creation."""
    created: Dict[str, Any] = {"wiki_pages": [], "wiki_categories": [], "wiki_revisions": []}
    p = _pages()
    c = _cats()
    r = _revs()
    try:
        created["wiki_pages"].append(p.create_index([("slug", ASCENDING)], name="slug_unique", unique=True))
    except Exception as e:
        created["wiki_pages"].append(f"slug_unique: {e}")
    try:
        created["wiki_pages"].append(p.create_index([("status", ASCENDING), ("updated_at", DESCENDING)], name="status_updated"))
        created["wiki_pages"].append(p.create_index([("status", ASCENDING), ("created_at", DESCENDING)], name="status_created"))
        created["wiki_pages"].append(p.create_index([("tags", ASCENDING)], name="tags"))
        created["wiki_pages"].append(p.create_index([("category_ids", ASCENDING)], name="catids"))
        # Optional text search index; list endpoint uses regex so this is not required
        created["wiki_pages"].append(p.create_index([("title", TEXT), ("summary", TEXT), ("plain_text", TEXT)], name="text"))
    except Exception as e:
        created["wiki_pages"].append(f"misc: {e}")
    try:
        created["wiki_revisions"].append(r.create_index([("page_id", ASCENDING), ("created_at", DESCENDING)], name="page_time"))
    except Exception as e:
        created["wiki_revisions"].append(f"page_time: {e}")
    try:
        created["wiki_categories"].append(c.create_index([("slug", ASCENDING)], unique=True, name="cat_slug"))
        created["wiki_categories"].append(c.create_index([("parent_id", ASCENDING)], name="cat_parent"))
        created["wiki_categories"].append(c.create_index([("position", ASCENDING), ("name", ASCENDING)], name="cat_order"))
    except Exception as e:
        created["wiki_categories"].append(f"cat_idx: {e}")
    return created

# Try at import, ignore failures (e.g., DB not ready yet)
try:
    _ensure_indexes()
except Exception:
    pass

# ------------------------------- models ------------------------------------- #

Str120 = Annotated[str, StringConstraints(min_length=2, max_length=120)]
Str200 = Annotated[str, StringConstraints(min_length=2, max_length=200)]
FmtHtmlOrMd = Annotated[str, StringConstraints(pattern=r"^(html|markdown)$")]

class CategoryIn(BaseModel):
    name: Str120
    parent_id: Optional[str] = None
    description: Optional[str] = ""
    position: int = 0

class CategoryOut(BaseModel):
    id: str
    name: str
    slug: str
    parent_id: Optional[str] = None
    description: Optional[str] = ""
    position: int = 0

class PageCreate(BaseModel):
    title: Str200
    summary: Optional[str] = ""
    content_html: Optional[str] = ""
    content_markdown: Optional[str] = ""
    content_format: FmtHtmlOrMd = "html"
    tags: List[str] = Field(default_factory=list)
    category_ids: List[str] = Field(default_factory=list)
    images: List[str] = Field(default_factory=list)

class PageUpdate(BaseModel):
    title: Optional[Str200] = None
    summary: Optional[str] = None
    content_html: Optional[str] = None
    content_markdown: Optional[str] = None
    content_format: Optional[FmtHtmlOrMd] = None
    tags: Optional[List[str]] = None
    category_ids: Optional[List[str]] = None
    images: Optional[List[str]] = None
    revision_note: Optional[str] = ""

# ------------------------------ categories ---------------------------------- #

@router.post("/categories", dependencies=[Depends(_require_admin)], response_model=CategoryOut)
def create_category(payload: CategoryIn):
    base_slug = slugify(payload.name)
    slug = base_slug
    if _cats().count_documents({"slug": slug}):
        i = 2
        while _cats().count_documents({"slug": f"{base_slug}-{i}"}):
            i += 1
        slug = f"{base_slug}-{i}"
    doc = {
        "name": payload.name.strip(),
        "slug": slug,
        "parent_id": _oid(payload.parent_id),
        "description": payload.description or "",
        "position": payload.position or 0,
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    try:
        _cats().insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "Category slug already exists.")
    return {
        "id": str(doc["_id"]),
        "name": doc["name"],
        "slug": doc["slug"],
        "parent_id": str(doc["parent_id"]) if doc.get("parent_id") else None,
        "description": doc.get("description", ""),
        "position": doc.get("position", 0),
    }

@router.get("/categories", response_model=List[CategoryOut])
def list_categories(parent_id: Optional[str] = None):
    q: Dict[str, Any] = {}
    if parent_id:
        q["parent_id"] = _oid(parent_id)
    out: List[CategoryOut] = []
    for c in _cats().find(q).sort([("position", ASCENDING), ("name", ASCENDING)]):
        out.append(CategoryOut(
            id=str(c["_id"]),
            name=c["name"],
            slug=c["slug"],
            parent_id=str(c["parent_id"]) if c.get("parent_id") else None,
            description=c.get("description", ""),
            position=c.get("position", 0),
        ))
    return out

@router.get("/categories/tree")
def categories_tree():
    """Nested categories for the Wiki Home sidebar."""
    docs = list(_cats().find({}, projection={"slug": 1, "name": 1, "parent_id": 1, "position": 1}))
    nodes: Dict[str, Dict[str, Any]] = {
        str(d["_id"]): {
            "id": str(d["_id"]),
            "slug": d["slug"],
            "name": d["name"],
            "parent_id": str(d["parent_id"]) if d.get("parent_id") else None,
            "position": d.get("position", 0),
            "children": [],
        } for d in docs
    }
    roots: List[Dict[str, Any]] = []
    for d in docs:
        node = nodes[str(d["_id"])]
        pid = d.get("parent_id")
        if pid and str(pid) in nodes:
            nodes[str(pid)]["children"].append(node)
        else:
            roots.append(node)

    def _sort_rec(items: List[Dict[str, Any]]):
        items.sort(key=lambda n: (n.get("position") or 0, (n.get("name") or "").lower()))
        for ch in items:
            _sort_rec(ch["children"])

    _sort_rec(roots)
    # Return under "tree" so your Portal code's `catsData.tree || catsData || []` works.
    return {"tree": roots}

# -------------------------------- pages ------------------------------------- #

@router.post("/pages")
def create_page(payload: PageCreate):
    cat_ids = [x for x in (_oid(v) for v in (payload.category_ids or [])) if x]
    slug = _unique_slug(payload.title)
    doc = {
        "slug": slug,
        "title": payload.title.strip(),
        "summary": (payload.summary or "").strip(),
        "content_html": payload.content_html or "",
        "content_markdown": payload.content_markdown or "",
        "content_format": payload.content_format or "html",
        "plain_text": _plain_text_from_html(payload.content_html or ""),
        "tags": sorted(list({t.strip().lower() for t in (payload.tags or []) if t.strip()})),
        "category_ids": cat_ids,
        "categories": [],           # optional denormalized names
        "category_path": [],        # optional breadcrumb
        "images": payload.images or [],
        "status": "draft",          # draft -> pending -> published
        "created_at": now_utc(),
        "updated_at": now_utc(),
        "published_at": None,
        "author_id": None,          # hook your auth here if needed
        "views": 0,
        "likes": 0,
    }
    _pages().insert_one(doc)
    _record_revision(doc["_id"], doc, note="created")
    return _page_public(doc)

@router.get("/pages")
def list_pages(
    q: Optional[str] = Query(None, description="Free text query (title/summary/content)"),
    status: str = Query("published", description="draft|pending|published|rejected"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    category_id: Optional[str] = Query(None, description="Filter by category ObjectId"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort: str = Query("new", pattern="^(new|updated|popular)$"),
):
    """
    Recent/search results for wiki pages.
    Powers:
      - GET /api/wiki/pages?status=published&limit=20
      - GET /api/wiki/pages?q=...&status=published
    """
    filt: Dict[str, Any] = {"status": status}
    if tag:
        filt["tags"] = tag.strip().lower()
    if category_id:
        cid = _oid(category_id)
        if cid:
            filt["category_ids"] = cid
    if q:
        # Regex-based search (no text index required)
        filt["$or"] = [
            {"title": {"$regex": q, "$options": "i"}},
            {"summary": {"$regex": q, "$options": "i"}},
            {"plain_text": {"$regex": q, "$options": "i"}},
        ]

    if sort == "new":
        order = [("created_at", -1)]
    elif sort == "updated":
        order = [("updated_at", -1), ("created_at", -1)]
    else:  # popular
        order = [("views", -1), ("likes", -1), ("updated_at", -1)]

    cur = (
        _pages()
        .find(filt, projection={
            "slug": 1, "title": 1, "summary": 1, "plain_text": 1,
            "status": 1, "tags": 1, "category_ids": 1, "category": 1, "category_path": 1,
            "created_at": 1, "updated_at": 1, "views": 1, "likes": 1,
        })
        .sort(order)
        .skip(offset)
        .limit(limit)
    )
    docs = list(cur)
    total = _pages().count_documents(filt)
    return {
        "items": [_page_list_item(d) for d in docs],
        "total": total,
        "limit": limit,
        "offset": offset,
        "query": q,
    }

@router.get("/pages/{slug}")
def get_page(slug: str):
    doc = _pages().find_one({"slug": slug, "status": "published"})
    if not doc:
        raise HTTPException(404, "Page not found.")
    # Optional: increment views (best-effort)
    try:
        _pages().update_one({"_id": doc["_id"]}, {"$inc": {"views": 1}})
    except Exception:
        pass
    return _page_public(doc)

@router.patch("/pages/{slug}", dependencies=[Depends(_require_admin)])
def update_page(slug: str, payload: PageUpdate):
    doc = _pages().find_one({"slug": slug})
    if not doc:
        raise HTTPException(404, "Page not found.")

    updates: Dict[str, Any] = {}

    # title/slug
    if payload.title is not None and payload.title.strip() and payload.title != doc.get("title"):
        updates["title"] = payload.title.strip()
        updates["slug"] = _unique_slug(payload.title, ignore_id=doc["_id"])

    # content + summary
    for k in ["summary", "content_html", "content_markdown", "content_format"]:
        v = getattr(payload, k)
        if v is not None:
            updates[k] = v

    if "content_html" in updates:
        updates["plain_text"] = _plain_text_from_html(updates.get("content_html", ""))

    # tags
    if payload.tags is not None:
        updates["tags"] = sorted(
            list({t.strip().lower() for t in (payload.tags or []) if t.strip()})
        )

    # categories
    if payload.category_ids is not None:
        updates["category_ids"] = [x for x in (_oid(v) for v in payload.category_ids) if x]

    # images
    if payload.images is not None:
        updates["images"] = payload.images or []

    if not updates:
        return _page_public(doc)

    updates["updated_at"] = now_utc()
    _pages().update_one({"_id": doc["_id"]}, {"$set": updates})
    doc = _pages().find_one({"_id": doc["_id"]})
    _record_revision(doc["_id"], {**doc, **updates}, note=payload.revision_note or "updated")
    return _page_public(doc)

@router.post("/pages/{slug}/submit", dependencies=[Depends(_require_admin)])
def submit_for_review(slug: str):
    res = _pages().update_one({"slug": slug}, {"$set": {"status": "pending", "updated_at": now_utc()}})
    if not res.matched_count:
        raise HTTPException(404, "Page not found.")
    return {"ok": True, "status": "pending"}

@router.post("/pages/{slug}/publish", dependencies=[Depends(_require_admin)])
def approve_and_publish(slug: str):
    res = _pages().update_one(
        {"slug": slug},
        {"$set": {"status": "published", "published_at": now_utc(), "updated_at": now_utc()}},
    )
    if not res.matched_count:
        raise HTTPException(404, "Page not found.")
    return {"ok": True, "status": "published"}

@router.get("/pages/{slug}/revisions")
def list_revisions(slug: str):
    page = _pages().find_one({"slug": slug})
    if not page:
        raise HTTPException(404, "Page not found.")
    revs = list(_revs().find({"page_id": page["_id"]}).sort("created_at", DESCENDING))
    return [{
        "id": str(r["_id"]),
        "created_at": r["created_at"],
        "title": r.get("title"),
        "note": r.get("note", ""),
        "tags": r.get("tags", []),
    } for r in revs]

# -------------------------------- tags -------------------------------------- #

@router.get("/tags")
def list_tags(limit: int = Query(50, ge=1, le=200), status: str = Query("published")):
    """
    Popular tags across pages with given status (default: published).
    Returns: { items: [{ name, count }, ...] }
    """
    pipeline = [
        {"$match": {"status": status, "tags": {"$exists": True, "$ne": []}}},
        {"$unwind": "$tags"},
        {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
        {"$limit": limit},
    ]
    rows = list(_pages().aggregate(pipeline))
    return {"items": [{"name": r["_id"], "count": r["count"]} for r in rows]}

# -------------------------------- media ------------------------------------- #

try:
    from gridfs import GridFS
    _fs = GridFS(get_db(), collection="wiki_media")
except Exception:
    _fs = None  # Media endpoints will 503 if GridFS can’t be created

@router.post("/media")
def upload_media(
    file: Annotated[UploadFile, File(...)],
    folder: Annotated[Optional[str], Form(...)] = "",
):
    if _fs is None:
        raise HTTPException(503, "Media storage not available.")
    data = file.file.read()
    fid = _fs.put(
        data,
        filename=file.filename,
        content_type=file.content_type or "application/octet-stream",
        metadata={"folder": folder, "uploaded_at": now_utc().isoformat()},
    )
    return {
        "id": str(fid),
        "url": f"/api/wiki/media/{fid}",
        "filename": file.filename,
        "content_type": file.content_type,
    }

@router.get("/media/{file_id}")
def get_media(file_id: str):
    if _fs is None:
        raise HTTPException(503, "Media storage not available.")
    try:
        fobj = _fs.get(ObjectId(file_id))
    except Exception:
        raise HTTPException(404, "File not found.")
    media_type = getattr(fobj, "content_type", None) or "application/octet-stream"
    return Response(content=fobj.read(), media_type=media_type)

# -------------------------------- misc -------------------------------------- #

@router.get("/_health")
def healthcheck():
    try:
        _ensure_indexes()
        _pages().estimated_document_count()  # touch collection
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}

@router.post("/_ensure_indexes", dependencies=[Depends(_require_admin)])
def ensure_wiki_indexes():
    """Manual index creation endpoint (idempotent)."""
    created = _ensure_indexes()
    return {"ok": True, "created": created}