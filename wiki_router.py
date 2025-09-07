# wiki_router.py (Pylance-friendly)
from __future__ import annotations

from fastapi import (
    APIRouter,
    HTTPException,
    Depends,
    UploadFile,
    File,
    Form,
    Query,
    Header,
    Response,
)
from typing import Optional, List, Dict, Any, Annotated
from pydantic import BaseModel, Field, StringConstraints
from datetime import datetime, timezone
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, TEXT
from pymongo.errors import DuplicateKeyError
import re
import os

from db_mongo import get_col, get_db, norm_key

router = APIRouter(prefix="/wiki", tags=["wiki"])

# Collections
_pages = get_col("wiki_pages")
_revs = get_col("wiki_revisions")
_cats = get_col("wiki_categories")

# GridFS for media (images, etc.)
try:
    from gridfs import GridFS
    _fs = GridFS(get_db(), collection="wiki_media")
except Exception:
    _fs = None  # Media endpoints will 503 if GridFS can’t be created

# ---------- helpers ----------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def oid(val: Optional[str]) -> Optional[ObjectId]:
    if not val:
        return None
    try:
        return ObjectId(val)
    except Exception:
        return None

SLUG_RE = re.compile(r"[^a-z0-9\-]+")

def slugify(title: str) -> str:
    s = norm_key(title or "").lower().replace("_", "-")
    s = SLUG_RE.sub("-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "page"

def _ensure_indexes() -> None:
    # pages
    _pages.create_index([("slug", ASCENDING)], name="slug_unique", unique=True)
    _pages.create_index([("status", ASCENDING), ("updated_at", DESCENDING)], name="status_updated")
    _pages.create_index([("tags", ASCENDING)], name="tags")
    _pages.create_index([("category_ids", ASCENDING)], name="catids")
    _pages.create_index([("title", TEXT), ("plain_text", TEXT), ("tags", TEXT)], name="text")
    # revisions
    _revs.create_index([("page_id", ASCENDING), ("created_at", DESCENDING)], name="page_time")
    # categories
    _cats.create_index([("slug", ASCENDING)], unique=True, name="cat_slug")
    _cats.create_index([("parent_id", ASCENDING)], name="cat_parent")

# try at import; if DB isn’t ready this will be retried on first request via /_health
try:
    _ensure_indexes()
except Exception:
    pass

def _require_admin(x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token")) -> None:
    needed = os.getenv("WIKI_ADMIN_TOKEN")
    if not needed:
        # No token configured -> allow all (useful for local dev).
        return
    if x_admin_token != needed:
        raise HTTPException(status_code=403, detail="Admin token required.")

def _plain_text_from_html(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "").strip()

def _unique_slug(base: str, ignore_id: Optional[ObjectId] = None) -> str:
    slug = slugify(base) or "page"
    n = 1
    while True:
        q = {"slug": slug}
        if ignore_id:
            q["_id"] = {"$ne": ignore_id}
        if _pages.count_documents(q, limit=1) == 0:
            return slug
        n += 1
        slug = f"{slug}-{n}"

def _record_revision(page_id: ObjectId, data: Dict[str, Any], note: str = "") -> None:
    _revs.insert_one({
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
    return {
        "id": str(doc["_id"]),
        "slug": doc["slug"],
        "title": doc["title"],
        "summary": doc.get("summary", ""),
        "content_html": doc.get("content_html", ""),
        "content_markdown": doc.get("content_markdown", ""),
        "content_format": doc.get("content_format", "html"),
        "status": doc["status"],
        "tags": doc.get("tags", []),
        "category_ids": [str(x) for x in doc.get("category_ids", [])],
        "categories": doc.get("categories", []),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "published_at": doc.get("published_at"),
        "author_id": str(doc["author_id"]) if doc.get("author_id") else None,
    }

# ---------- models ----------

Str120 = Annotated[str, StringConstraints(min_length=2, max_length=120)]
Str200 = Annotated[str, StringConstraints(min_length=2, max_length=200)]
FmtHtmlOrMd = Annotated[str, StringConstraints(pattern=r"^(html|markdown)$")]

class CategoryIn(BaseModel):
    name: Str120
    parent_id: Optional[str] = None
    description: Optional[str] = ""

class CategoryOut(BaseModel):
    id: str
    name: str
    slug: str
    parent_id: Optional[str] = None
    description: Optional[str] = ""

class PageCreate(BaseModel):
    title: Str200
    summary: Optional[str] = ""
    content_html: Optional[str] = ""
    content_markdown: Optional[str] = ""
    content_format: FmtHtmlOrMd = "html"
    tags: List[str] = Field(default_factory=list)
    category_ids: List[str] = Field(default_factory=list)

class PageUpdate(BaseModel):
    title: Optional[Str200] = None
    summary: Optional[str] = None
    content_html: Optional[str] = None
    content_markdown: Optional[str] = None
    content_format: Optional[FmtHtmlOrMd] = None
    tags: Optional[List[str]] = None
    category_ids: Optional[List[str]] = None
    revision_note: Optional[str] = ""

class PageOut(BaseModel):
    id: str
    slug: str
    title: str
    summary: str
    content_html: str
    content_markdown: str
    content_format: str
    status: str
    tags: List[str]
    category_ids: List[str]
    categories: Optional[List[str]] = None
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime] = None
    author_id: Optional[str] = None

# ---------- categories ----------

@router.post("/categories", dependencies=[Depends(_require_admin)], response_model=CategoryOut)
def create_category(payload: CategoryIn):
    try:
        base_slug = slugify(payload.name)
        slug = base_slug
        if _cats.count_documents({"slug": base_slug}):
            # Keep unique if name reused
            i = 2
            while _cats.count_documents({"slug": f"{base_slug}-{i}"}):
                i += 1
            slug = f"{base_slug}-{i}"
        doc = {
            "name": payload.name.strip(),
            "slug": slug,
            "parent_id": oid(payload.parent_id),
            "description": payload.description or "",
            "created_at": now_utc(),
            "updated_at": now_utc(),
        }
        _cats.insert_one(doc)
        return {
            "id": str(doc["_id"]),
            "name": doc["name"],
            "slug": doc["slug"],
            "parent_id": str(doc["parent_id"]) if doc["parent_id"] else None,
            "description": doc["description"],
        }
    except DuplicateKeyError:
        raise HTTPException(409, "Category slug already exists.")

@router.get("/categories", response_model=List[CategoryOut])
def list_categories(parent_id: Optional[str] = None):
    q: Dict[str, Any] = {}
    if parent_id:
        q["parent_id"] = oid(parent_id)
    out: List[CategoryOut] = []
    for c in _cats.find(q).sort("name", ASCENDING):
        out.append(CategoryOut(
            id=str(c["_id"]),
            name=c["name"],
            slug=c["slug"],
            parent_id=str(c["parent_id"]) if c.get("parent_id") else None,
            description=c.get("description", ""),
        ))
    return out

@router.get("/categories/tree")
def categories_tree():
    docs = list(_cats.find({}))
    nodes = {str(d["_id"]): {"id": str(d["_id"]), "name": d["name"], "slug": d["slug"], "children": []} for d in docs}
    root: List[Dict[str, Any]] = []
    for d in docs:
        pid = d.get("parent_id")
        node = nodes[str(d["_id"])]
        if pid and str(pid) in nodes:
            nodes[str(pid)]["children"].append(node)
        else:
            root.append(node)
    return root

# ---------- pages ----------

@router.post("/pages", response_model=PageOut)
def create_page(payload: PageCreate):
    cat_ids = [oid(x) for x in payload.category_ids if oid(x)]
    slug = _unique_slug(payload.title)
    doc = {
        "slug": slug,
        "title": payload.title.strip(),
        "summary": payload.summary or "",
        "content_html": payload.content_html or "",
        "content_markdown": payload.content_markdown or "",
        "content_format": payload.content_format or "html",
        "plain_text": _plain_text_from_html(payload.content_html or ""),
        "tags": sorted(list({t.strip().lower() for t in (payload.tags or []) if t.strip()})),
        "category_ids": cat_ids,
        "categories": [],  # optional denormalized names
        "status": "draft",  # draft -> pending -> published
        "created_at": now_utc(),
        "updated_at": now_utc(),
        "published_at": None,
        "author_id": None,  # hook your auth here if needed
    }
    _pages.insert_one(doc)
    _record_revision(doc["_id"], doc, note="created")
    return _page_public(doc)

@router.get("/pages/{slug}", response_model=PageOut)
def get_page(slug: str):
    doc = _pages.find_one({"slug": slug})
    if not doc:
        raise HTTPException(404, "Page not found.")
    if doc.get("status") != "published":
        raise HTTPException(403, "Page is not published yet.")
    return _page_public(doc)

@router.get("/pages", response_model=List[PageOut])
def list_pages(
    q: Annotated[Optional[str], Query(default=None, description="Full-text search")] = None,
    tag: Optional[str] = None,
    category_id: Optional[str] = None,
    status: str = "published",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    skip: Annotated[int, Query(ge=0)] = 0,
):
    query: Dict[str, Any] = {"status": status}
    if q:
        query["$text"] = {"$search": q}
    if tag:
        query["tags"] = tag.strip().lower()
    if category_id:
        query["category_ids"] = oid(category_id)
    docs = list(_pages.find(query).sort("updated_at", DESCENDING).skip(skip).limit(min(limit, 200)))
    return [_page_public(d) for d in docs]

@router.patch("/pages/{slug}", response_model=PageOut, dependencies=[Depends(_require_admin)])
def update_page(slug: str, payload: PageUpdate):
    doc = _pages.find_one({"slug": slug})
    if not doc:
        raise HTTPException(404, "Page not found.")
    updates: Dict[str, Any] = {}

    if payload.title is not None and payload.title.strip() and payload.title != doc.get("title"):
        updates["title"] = payload.title.strip()
        updates["slug"] = _unique_slug(payload.title, ignore_id=doc["_id"])

    for k in ["summary", "content_html", "content_markdown", "content_format"]:
        v = getattr(payload, k)
        if v is not None:
            updates[k] = v

    if payload.tags is not None:
        updates["tags"] = sorted(list({t.strip().lower() for t in (payload.tags or []) if t.strip()}))

    if payload.category_ids is not None:
        updates["category_ids"] = [oid(x) for x in payload.category_ids if oid(x)]

    if "content_html" in updates:
        updates["plain_text"] = _plain_text_from_html(updates.get("content_html", ""))

    if not updates:
        return _page_public(doc)

    updates["updated_at"] = now_utc()
    _pages.update_one({"_id": doc["_id"]}, {"$set": updates})
    doc = _pages.find_one({"_id": doc["_id"]})
    _record_revision(doc["_id"], {**doc, **updates}, note=payload.revision_note or "updated")
    return _page_public(doc)

@router.post("/pages/{slug}/submit", dependencies=[Depends(_require_admin)])
def submit_for_review(slug: str):
    res = _pages.update_one({"slug": slug}, {"$set": {"status": "pending", "updated_at": now_utc()}})
    if not res.matched_count:
        raise HTTPException(404, "Page not found.")
    return {"ok": True, "status": "pending"}

@router.post("/pages/{slug}/publish", dependencies=[Depends(_require_admin)])
def approve_and_publish(slug: str):
    res = _pages.update_one(
        {"slug": slug},
        {"$set": {"status": "published", "published_at": now_utc(), "updated_at": now_utc()}},
    )
    if not res.matched_count:
        raise HTTPException(404, "Page not found.")
    return {"ok": True, "status": "published"}

@router.get("/pages/{slug}/revisions")
def list_revisions(slug: str):
    page = _pages.find_one({"slug": slug})
    if not page:
        raise HTTPException(404, "Page not found.")
    revs = list(_revs.find({"page_id": page["_id"]}).sort("created_at", DESCENDING))
    return [{
        "id": str(r["_id"]),
        "created_at": r["created_at"],
        "title": r.get("title"),
        "note": r.get("note", ""),
        "tags": r.get("tags", []),
    } for r in revs]

# ---------- tags ----------

@router.get("/tags")
def list_tags(limit: int = 50):
    pipeline = [
        {"$unwind": "$tags"},
        {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": min(limit, 200)},
    ]
    return [{"tag": d["_id"], "count": d["count"]} for d in _pages.aggregate(pipeline)]

# ---------- media ----------

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
    return {"id": str(fid), "url": f"/api/wiki/media/{fid}", "filename": file.filename, "content_type": file.content_type}

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

# ---------- health ----------

@router.get("/_health")
def healthcheck():
    try:
        _ensure_indexes()
    except Exception:
        pass
    return {"ok": True}

# ---------- Helpers ----------

def _oid(value: Optional[str]) -> Optional[ObjectId]:
    """Convert 24-hex string to ObjectId; return None if not valid."""
    if not value:
        return None
    try:
        return ObjectId(value)
    except Exception:
        return None

def _serialize_id(v: Any) -> Optional[str]:
    return str(v) if isinstance(v, ObjectId) else v

def _serialize_page(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Return a front-end friendly page object."""
    return {
        "id": _serialize_id(doc.get("_id")),
        "slug": doc.get("slug"),
        "title": doc.get("title"),
        "summary": doc.get("summary") or doc.get("excerpt"),
        "status": doc.get("status"),
        "tags": doc.get("tags") or [],
        "category": (
            {"id": _serialize_id(doc.get("category_id")),
             "slug": doc.get("category_slug"),
             "name": doc.get("category_name")}
            if doc.get("category_id") or doc.get("category_slug") else None
        ),
        "updated_at": doc.get("updated_at"),
        "created_at": doc.get("created_at"),
        "views": doc.get("views") or 0,
        "likes": doc.get("likes") or 0,
        # omit heavy fields like "content" for listings
    }

def _serialize_category(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": _serialize_id(doc.get("_id")),
        "slug": doc.get("slug"),
        "name": doc.get("name"),
        "parent_id": _serialize_id(doc.get("parent_id")),
        "children": [],  # will be filled when building the tree
        "position": doc.get("position") or 0,
    }


# ---------- GET /api/wiki/pages ----------
@router.get("/pages")
def list_pages(
    q: Optional[str] = Query(None, description="Free text query (title/summary/content)"),
    status: Optional[str] = Query("published", description="draft|pending|published|rejected"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    category_id: Optional[str] = Query(None, description="Filter by category ObjectId"),
    category_slug: Optional[str] = Query(None, description="Filter by category slug"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort: str = Query("new", pattern="^(new|updated|popular)$"),
) -> Dict[str, Any]:
    """
    Returns recent/search results for wiki pages.
    This single endpoint powers:
      - Recent published pages (status=published&limit=20)
      - Search (q=...)
      - Filter by tag/category
    """
    pages = get_col("wiki_pages")

    # --- filter ---
    filt: Dict[str, Any] = {}
    if status:
        filt["status"] = status

    if tag:
        filt["tags"] = tag

    if category_slug:
        filt["category_slug"] = category_slug

    cid = _oid(category_id)
    if cid:
        filt["category_id"] = cid

    # Text-ish search (regex to avoid requiring a Mongo text index)
    if q:
        filt["$or"] = [
            {"title": {"$regex": q, "$options": "i"}},
            {"summary": {"$regex": q, "$options": "i"}},
            {"content": {"$regex": q, "$options": "i"}},
        ]

    # --- sort ---
    if sort == "new":
        order = [("created_at", -1)]
    elif sort == "updated":
        order = [("updated_at", -1), ("created_at", -1)]
    else:  # "popular"
        order = [("views", -1), ("likes", -1), ("updated_at", -1)]

    cursor = (
        pages.find(filt, projection={
            "title": 1, "slug": 1, "summary": 1, "status": 1,
            "tags": 1, "category_id": 1, "category_slug": 1, "category_name": 1,
            "updated_at": 1, "created_at": 1, "views": 1, "likes": 1,
        })
        .sort(order)
        .skip(offset)
        .limit(limit)
    )

    docs = list(cursor)
    total = pages.count_documents(filt)

    return {
        "items": [_serialize_page(d) for d in docs],
        "total": total,
        "limit": limit,
        "offset": offset,
        "query": q,
    }


# ---------- GET /api/wiki/categories/tree ----------
@router.get("/categories/tree")
def categories_tree() -> Dict[str, Any]:
    """
    Returns a nested tree of categories.
    Each category doc supports: { _id, slug, name, parent_id?, position? }
    """
    col = get_col("wiki_categories")
    raw = list(
        col.find({}, projection={"slug": 1, "name": 1, "parent_id": 1, "position": 1})
        .sort([("position", 1), ("name", 1)])
    )

    nodes: Dict[str, Dict[str, Any]] = {}
    roots: List[Dict[str, Any]] = []

    for d in raw:
        node = _serialize_category(d)
        nodes[node["id"]] = node

    for node in nodes.values():
        pid = node["parent_id"]
        if pid and pid in nodes:
            nodes[pid]["children"].append(node)
        else:
            roots.append(node)

    # sort children by position/name
    def _sort_rec(lst: List[Dict[str, Any]]):
        lst.sort(key=lambda n: (n.get("position") or 0, (n.get("name") or "").lower()))
        for ch in lst:
            _sort_rec(ch["children"])

    _sort_rec(roots)
    return {"items": roots}


# ---------- GET /api/wiki/tags ----------
@router.get("/tags")
def popular_tags(
    limit: int = Query(50, ge=1, le=200),
    status: str = Query("published", description="Count tags from pages with this status"),
) -> Dict[str, Any]:
    """
    Returns the most common tags across pages (default: published).
    Output: [{ "name": "tag", "count": n }, ...]
    """
    pages = get_col("wiki_pages")
    pipeline = [
        {"$match": {"status": status, "tags": {"$exists": True, "$ne": []}}},
        {"$unwind": "$tags"},
        {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
        {"$limit": limit},
    ]
    rows = list(pages.aggregate(pipeline))
    return {"items": [{"name": r["_id"], "count": r["count"]} for r in rows]}


# ---------- (Optional) one-off index helper ----------
@router.post("/_ensure_indexes")
def ensure_wiki_indexes() -> Dict[str, Any]:
    """
    Safe to call at deploy time (idempotent).
    Creates helpful indexes but the API does not *require* them to run.
    """
    pages = get_col("wiki_pages")
    cats = get_col("wiki_categories")

    created: Dict[str, Any] = {
        "wiki_pages": [],
        "wiki_categories": [],
    }

    try:
        # speed up common filters/sorts
        created["wiki_pages"].append(
            pages.create_index([("status", 1), ("created_at", -1)])
        )
        created["wiki_pages"].append(
            pages.create_index([("status", 1), ("updated_at", -1)])
        )
        created["wiki_pages"].append(pages.create_index("tags"))
        created["wiki_pages"].append(pages.create_index("category_id"))
        created["wiki_pages"].append(pages.create_index("category_slug"))
        created["wiki_pages"].append(pages.create_index("slug", unique=True))
        # Optional text index; only useful if you switch search to $text
        created["wiki_pages"].append(
            pages.create_index([("title", "text"), ("summary", "text"), ("content", "text")])
        )
    except Exception as e:
        created["wiki_pages"].append(f"index_error: {e}")

    try:
        created["wiki_categories"].append(cats.create_index("slug", unique=True))
        created["wiki_categories"].append(cats.create_index("parent_id"))
        created["wiki_categories"].append(cats.create_index([("position", 1), ("name", 1)]))
    except Exception as e:
        created["wiki_categories"].append(f"index_error: {e}")

    return {"ok": True, "created": created}


@router.get("/pages/{slug}")
def get_page_by_slug(slug: str):
    col = get_col("wiki_pages")
    doc = col.find_one({"slug": slug, "status": "published"})
    if not doc:
        raise HTTPException(status_code=404, detail="Page not found")
    # Optional: increment views
    try:
        col.update_one({"_id": doc["_id"]}, {"$inc": {"views": 1}})
    except Exception:
        pass
    return {
        "id": str(doc["_id"]),
        "slug": doc.get("slug"),
        "title": doc.get("title"),
        "summary": doc.get("summary"),
        "content": doc.get("content"),
        "tags": doc.get("tags", []),
        "category": {
            "id": str(doc.get("category_id")) if doc.get("category_id") else None,
            "slug": doc.get("category_slug"),
            "name": doc.get("category_name"),
        } if (doc.get("category_id") or doc.get("category_slug")) else None,
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "views": doc.get("views", 0),
        "likes": doc.get("likes", 0),
    }
