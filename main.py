# main.py
import os
import logging
import secrets
import datetime
import re
import hashlib
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, Tuple, Optional

import uvicorn
from fastapi import FastAPI, Request, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import DuplicateKeyError

from db_mongo import get_col, next_id_str, get_db, ensure_indexes, sync_counters, norm_key, spell_sig

# Domain imports
from server.src.objects.effects import load_effect
from server.src.objects.spells import Spell
from server.src.modules.category_table import category_for_mp
from server.src.modules.apotheosis_constants import APO_STAGE_BASE, APO_TYPES, APO_TYPE_BONUS, P2S_COST, P2S_GAIN, P2A_COST, S2A_COST


# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("noe")

# ---------- Helpers ----------
def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def make_token() -> str:
    return secrets.token_hex(16)

def get_auth_token(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None

def verify_password(input_pw: str, user_doc: dict) -> bool:
    # accept plaintext ('password') or sha256 hash ('password_hash')
    return (
        user_doc.get("password") == input_pw
        or user_doc.get("password_hash") == _sha256(input_pw)
    )

def normalize_email(email: str) -> str:
    return (email or "").strip().lower()

_ALLOWED_ROLES = {"user", "moderator", "admin"}

def find_user(username: str) -> Optional[dict]:
    # always exclude _id when returning data to the app
    return get_col("users").find_one({"username": username}, {"_id": 0})

def require_auth(request: Request, roles: Optional[list[str]] = None) -> Tuple[str, str]:
    """Return (username, role) or raise Exception."""
    token = get_auth_token(request)
    if not token or token not in SESSIONS:
        raise Exception("Not authenticated")
    username, role = SESSIONS[token]
    if roles and role not in roles:
        raise Exception("Forbidden")
    return username, role

def write_audit(action, username, spell_id, before, after):
    get_col("audit_logs").insert_one({
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "user": username, "action": action, "spell_id": spell_id,
        "before": before, "after": after
    })

# ---- replace your helper with this ----
def compute_spell_costs(
    activation: str, range_val: int, aoe: str, duration: int, effect_ids: list[str]
) -> dict:
    try:
        effects = [load_effect(str(eid)) for eid in (effect_ids or [])]
    except Exception:
        docs = list(
            get_col("effects").find(
                {"id": {"$in": [str(eid) for eid in (effect_ids or [])]}},
                {"_id": 0, "mp_cost": 1, "en_cost": 1},
            )
        )
        class _E:
            def __init__(self, mp, en):
                self.mp_cost = int(mp or 0)
                self.en_cost = int(en or 0)
        effects = [_E(d.get("mp_cost", 0), d.get("en_cost", 0)) for d in docs]

    mp_cost, en_cost, breakdown = Spell.compute_cost(
        range_val, aoe, duration, activation, effects
    )

    return {
        "mp_cost": mp_cost,
        "en_cost": en_cost,
        "category": category_for_mp(mp_cost),
        "mp_to_next_category": mp_to_next_category_delta(mp_cost),
        "breakdown": breakdown,
    }

# ---------- Lifespan (startup/shutdown) ----------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure indexes and counters are ready on boot
    ensure_indexes()
    sync_counters()

    # Seed admin if provided via env
    u = os.getenv("ADMIN_USER")
    p = os.getenv("ADMIN_PASSWORD")
    if u and p and not get_col("users").find_one({"username": u}):
        get_col("users").update_one(
            {"username": u},
            {"$set": {"username": u, "password_hash": _sha256(p), "role": "admin"}},
            upsert=True,
        )
        logger.info("Seeded admin user '%s' from env", u)

    yield


# ---------- App ----------
app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSIONS: Dict[str, Tuple[str, str]] = {}  # token -> (username, role)

BASE_DIR = Path(__file__).resolve().parent
CLIENT_DIR = BASE_DIR / "client"

# Serve all client assets (css/js/images) from /static
app.mount("/static", StaticFiles(directory=str(CLIENT_DIR)), name="static")

# Allow-listed html pages
ALLOWED_PAGES = {"home", "index", "scraper", "templates", "admin", "export", "user_management","signup","browse","browse_effects","browse_schools","portal","apotheosis_home","apotheosis_create","apotheosis_browse","apotheosis_parse_constraints","apotheosis_constraints"}

# ---------- Pages ----------
@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/portal.html")

@app.get("/{page}.html", include_in_schema=False)
def serve_page(page: str):
    if page in ALLOWED_PAGES:
        return FileResponse(CLIENT_DIR / f"{page}.html")
    raise HTTPException(404, "Page not found")

# ---------- Auth ----------
@app.post("/auth/login")
async def auth_login(request: Request):
    body = await request.json()
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        return {"status": "error", "message": "Missing username or password"}

    user = find_user(username)
    if not user or not verify_password(password, user):
        logger.info("Login failed for user=%s", username)
        return {"status": "error", "message": "Login failed"}

    token = make_token()
    role = user.get("role", "user")
    SESSIONS[token] = (username, role)
    logger.info("Login ok: %s (%s)", username, role)
    return {"status": "success", "token": token, "username": username, "role": role}

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


# ---------- Reference Data ----------
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
        })
    out.sort(key=lambda x: x["name"].lower())
    return {"schools": out}

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
@app.post("/admin/effects/bulk_create")  # alias; keeps old/new frontends working
async def bulk_create_effects(request: Request):
    # 1) Auth gate with clear errors
    try:
        require_auth(request, ["admin", "moderator"])
    except Exception as e:
        msg = str(e)
        code = 401 if "Not authenticated" in msg else 403
        return JSONResponse({"status": "error", "message": msg}, status_code=code)

    # 2) Parse body outside the broad try so JSON errors are distinct
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON"}, status_code=400)

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

        # find-or-create school
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

        # (Optional) light duplicate guard for effects in this batch: (name, mp, en) within same school
        created = []
        for e in effects:
            name = (e.get("name") or "").strip()
            desc = (e.get("description") or "").strip()
            try:
                mp   = int(e.get("mp_cost"))
                en   = int(e.get("en_cost"))
            except Exception:
                return JSONResponse({"status":"error","message":f"Non-numeric MP/EN in effect '{name}'"}, status_code=400)

            # prevent obvious duplicates inside same school
            dup = eff_col.find_one(
                {"school": school["id"], "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}, "mp_cost": mp, "en_cost": en},
                {"_id": 1}
            )
            if dup:
                # skip silently or collect as 'skipped'; here we skip & continue
                continue

            eff_id = next_id_str("effects", padding=4)
            rec = {"id": eff_id, "name": name, "description": desc, "mp_cost": mp, "en_cost": en, "school": school["id"]}
            eff_col.insert_one(rec)
            created.append(eff_id)

        write_audit("bulk_create_effects", "admin-ui", "—", None, {"school": school, "created": created})
        return {"status": "success", "school": school, "created": created}

    except Exception as e:
        logger.exception("bulk_create_effects failed")
        return JSONResponse({"status":"error","message":str(e)}, status_code=500)


# ---------- Spells ----------
@app.get("/spells")
def list_spells(request: Request):
    qp = request.query_params
    name = qp.get("name") or None
    category = qp.get("category") or None
    school = qp.get("school") or None
    status = qp.get("status") or None
    fav_only = (qp.get("favorite") or qp.get("fav") or "").lower() in ("1", "true", "yes")


    try:
        page = max(1, int(qp.get("page") or 1))
    except Exception:
        page = 1
    try:
        limit = max(1, min(500, int(qp.get("limit") or 100)))
    except Exception:
        limit = 100

    sp_col  = get_col("spells")
    eff_col = get_col("effects")
    sch_col = get_col("schools")

    q = {}
    if name:
        q["name"] = {"$regex": name, "$options": "i"}
    if category:
        q["category"] = category
    if status:
        q["status"] = status.lower()
   
    fav_ids = None
    if fav_only:
        try:
            user, _ = require_user_doc(request)
        except HTTPException as he:
            # Not authenticated -> no results
            return {"spells": [], "page": page, "limit": limit, "total": 0, "error": he.detail}
        fav_ids = [str(x) for x in (user.get("favorites") or [])]
        if not fav_ids:
            return {"spells": [], "page": page, "limit": limit, "total": 0}
        q["id"] = {"$in": fav_ids}

    total = sp_col.count_documents(q)
    cursor = sp_col.find(q, {"_id": 0}).skip((page - 1) * limit).limit(limit)
    spells = list(cursor)

    # map school_id -> school_name
    school_map = {s["id"]: s.get("name", s["id"]) for s in sch_col.find({}, {"_id": 0, "id": 1, "name": 1})}

    # effect -> school
    all_eff_ids = {str(eid) for sp in spells for eid in (sp.get("effects") or [])}
    eff_docs = list(eff_col.find({"id": {"$in": list(all_eff_ids)}}, {"_id": 0, "id": 1, "school": 1}))
    eff_school = {d["id"]: str(d.get("school") or "") for d in eff_docs}

    # attach derived schools
    out = []
    for sp in spells:
        sch_ids = sorted({eff_school.get(str(eid), "") for eid in (sp.get("effects") or []) if eff_school.get(str(eid), "")})
        sp["schools"] = [{"id": sid, "name": school_map.get(sid, sid)} for sid in sch_ids]
        out.append(sp)

    if school:
        s_low = school.lower()
        out = [sp for sp in out if any(s["id"].lower() == s_low or s["name"].lower() == s_low for s in sp["schools"])]

    return {"spells": out, "page": page, "limit": limit, "total": total}

@app.get("/spells/{spell_id}")
def get_spell(spell_id: str):
    doc = get_col("spells").find_one({"id": spell_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, f"Spell {spell_id} not found")
    return {"spell": doc}

@app.put("/spells/{spell_id}")
async def update_spell(spell_id: str, request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "message": "Invalid JSON body"}, status_code=400)

    try:
        name        = (body.get("name") or "Unnamed Spell").strip()
        activation  = body.get("activation") or "Action"
        try:
            range_val = int(body.get("range", 0))
        except Exception:
            return JSONResponse({"status":"error","message":"range must be an integer"}, status_code=400)
        aoe_val     = body.get("aoe") or "A Square"
        try:
            duration  = int(body.get("duration", 1))
        except Exception:
            return JSONResponse({"status":"error","message":"duration must be an integer"}, status_code=400)

        effect_ids = [str(e).strip() for e in (body.get("effects") or []) if str(e).strip()]
        missing = [eid for eid in effect_ids if not get_col("effects").find_one({"id": eid}, {"_id": 1})]
        if missing:
            return JSONResponse({"status":"error","message":f"Unknown effect id(s): {', '.join(missing)}"}, status_code=400)

        cc = compute_spell_costs(activation, range_val, aoe_val, duration, effect_ids)

        doc = {
            "name": name,
            "activation": activation,
            "range": range_val,
            "aoe": aoe_val,
            "duration": duration,
            "effects": effect_ids,
            "mp_cost": cc["mp_cost"],
            "en_cost": cc["en_cost"],
            "category": cc["category"],
            "spell_type": body.get("spell_type") or "Simple",
            "moderation": "yellow",
        }

        r = get_col("spells").update_one({"id": spell_id}, {"$set": doc}, upsert=False)
        if r.matched_count == 0:
            return JSONResponse({"status": "error", "message": f"Spell {spell_id} not found"}, status_code=404)

        return {"status": "success", "id": spell_id, "spell": doc}

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

    cc = compute_spell_costs(activation, range_val, aoe_val, duration_val, effect_ids)
    return {
        "mp_cost": cc["mp_cost"],
        "en_cost": cc["en_cost"],
        "category": cc["category"],
        "mp_to_next_category": cc["mp_to_next_category"],
        "breakdown": cc["breakdown"],
    }

@app.post("/submit_spell")
async def submit_spell(request: Request):
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
        if not effect_ids:
            return JSONResponse({"status": "error", "message": "At least one effect is required."}, status_code=400)

        # verify effects exist
        missing = [eid for eid in effect_ids if not get_col("effects").find_one({"id": eid}, {"_id": 1})]
        if missing:
            return JSONResponse({"status": "error", "message": f"Unknown effect id(s): {', '.join(missing)}"}, status_code=400)

        # compute costs
        cc = compute_spell_costs(activation, range_val, aoe_val, duration, effect_ids)

        # signature over parameters (NOT name)
        sig = spell_sig(activation, range_val, aoe_val, duration, effect_ids)

        # duplicate check (do NOT reference a non-existent spell_id here)
        conflict = get_col("spells").find_one({"sig_v1": sig}, {"_id": 0, "id": 1, "name": 1})
        if conflict:
            return JSONResponse(
                {
                    "status": "error",
                    "message": f"Another spell with identical parameters already exists (id {conflict.get('id')}, name '{conflict.get('name','')}')."
                },
                status_code=409
            )

        # new id
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
            "mp_cost": cc["mp_cost"],
            "en_cost": cc["en_cost"],
            "category": cc["category"],
            "spell_type": body.get("spell_type") or "Simple",
            # default moderation status
            "status": "yellow",
        }

        get_col("spells").insert_one(dict(doc))
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

    # basic validation
    if not username or not email or not password or not confirm:
        return {"status": "error", "message": "All fields are required."}
    if "@" not in email or "." not in email.split("@")[-1]:
        return {"status": "error", "message": "Invalid email address."}
    if password != confirm:
        return {"status": "error", "message": "Passwords do not match."}
    if len(password) < 6:
        return {"status": "error", "message": "Password must be at least 6 characters."}

    users = get_col("users")

    # reject duplicates proactively (fast path)
    if users.find_one({"username": username}, {"_id": 1}):
        return {"status": "error", "message": "Username already taken."}
    if users.find_one({"email": email}, {"_id": 1}):
        return {"status": "error", "message": "Email already registered."}

    doc = {
        "username": username,
        "email": email,
        "password_hash": _sha256(password),  # consistent with your current login
        "role": "user",
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
    }

    try:
        users.insert_one(dict(doc))  # insert a copy (avoid _id leaking into response)
    except DuplicateKeyError:
        # In case of a race, rely on unique indexes to protect us:
        # figure out which field collided
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
    # sort by username
    users.sort(key=lambda u: u["username"].lower())
    return {"status": "success", "users": users}

@app.put("/admin/users/{target_username}/role")
async def admin_set_user_role(target_username: str, request: Request):
    admin_username, _ = require_auth(request, roles=["admin"])
    body = await request.json()
    role = (body.get("role") or "").strip().lower()

    if role not in _ALLOWED_ROLES:
        return JSONResponse({"status": "error", "message": "Invalid role."}, status_code=400)

    # Optional: block changing your own role if you want. For now, allow it.

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

    # Optional audit
    try:
        write_audit("set_status", username, spell_id, before=None, after={"status": status})
    except Exception:
        pass

    return {"status": "success", "id": spell_id, "new_status": status}

@app.delete("/admin/spells/flagged")
def delete_flagged_spells(request: Request):
    # Admin only
    require_auth(request, ["admin", "moderator"])
    r = get_col("spells").delete_many({"status": "red"})
    return {"status": "success", "deleted": r.deleted_count}

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


def _recompute_spells_for_effect(effect_id: str) -> tuple[str, int]:
    """
    Recompute every spell that references effect_id.
    Returns (patch_text, changed_count).
    """
    sp_col = get_col("spells")
    changed = 0
    lines: list[str] = []

    affected = list(sp_col.find({"effects": effect_id}, {"_id": 0}))
    if not affected:
        return ("No spells referenced this effect.", 0)

    for sp in affected:
        old_mp = int(sp.get("mp_cost", 0))
        old_en = int(sp.get("en_cost", 0))
        old_cat = sp.get("category", "")

        # recompute with current effect docs
        cc = compute_spell_costs(
            sp.get("activation", "Action"),
            int(sp.get("range", 0)),
            sp.get("aoe", "A Square"),
            int(sp.get("duration", 1)),
            [str(x) for x in (sp.get("effects") or [])]
        )

        new_mp, new_en, new_cat = cc["mp_cost"], cc["en_cost"], cc["category"]

        # Only write if something changed
        if (old_mp, old_en, old_cat) != (new_mp, new_en, new_cat):
            sp_col.update_one({"id": sp["id"]}, {"$set": {
                "mp_cost": new_mp,
                "en_cost": new_en,
                "category": new_cat
            }})
            changed += 1
            lines.append(
                f"[{sp['id']}] {sp.get('name','(unnamed)')}: "
                f"MP {old_mp} → {new_mp}, EN {old_en} → {new_en}, Category {old_cat} → {new_cat}"
            )

    if not lines:
        lines.append("No MP/EN/category changes after recompute.")
    return ("\n".join(lines), changed)


@app.put("/admin/effects/{effect_id}")
async def admin_update_effect(effect_id: str, request: Request):
    # moderators + admins
    require_auth(request, ["admin", "moderator"])
    body = await request.json()

    # Fetch old effect (for patch notes)
    col = get_col("effects")
    old = col.find_one({"id": effect_id}, {"_id": 0})
    if not old:
        return JSONResponse({"status":"error","message":"Effect not found"}, status_code=404)

    # Validate + build update
    name = (body.get("name") or old.get("name") or "").strip()
    desc = (body.get("description") or body.get("desc") or old.get("description") or "").strip()
    try:
        mp = int(body.get("mp_cost", old.get("mp_cost", 0)))
        en = int(body.get("en_cost", old.get("en_cost", 0)))
    except Exception:
        return JSONResponse({"status":"error","message":"MP/EN must be integers"}, status_code=400)

    school = str(body.get("school", old.get("school",""))).strip() or old.get("school","")

    # Update the effect first
    col.update_one({"id": effect_id}, {"$set": {
        "name": name, "description": desc, "mp_cost": mp, "en_cost": en, "school": school
    }})

    # Build patch header (effect changes)
    effect_changes = []
    def _chg(label, a, b):
        if a != b: effect_changes.append(f"{label}: {a} → {b}")

    _chg("Name", old.get("name",""), name)
    _chg("School", old.get("school",""), school)
    _chg("MP", int(old.get("mp_cost",0)), mp)
    _chg("EN", int(old.get("en_cost",0)), en)
    if (old.get("description","") != desc):
        effect_changes.append("Description: (updated)")

    header = [f"Edited Effect [{effect_id}]", ""] + ([*effect_changes, ""] if effect_changes else ["No direct field changes",""])

    # Recompute all spells using this effect
    spell_patch_text, changed_count = _recompute_spells_for_effect(effect_id)

    patch_text = "\n".join(header + ["Impacted Spells:", spell_patch_text]) + "\n"
    return {"status":"success","updated":effect_id,"changed_spells":changed_count,"patch_text":patch_text}


@app.delete("/admin/effects/{effect_id}")
def admin_delete_effect(effect_id: str, request: Request):
    # moderators + admins
    require_auth(request, ["admin", "moderator"])
    col = get_col("effects")
    old = col.find_one({"id": effect_id}, {"_id": 0})
    if not old:
        return {"status":"error","message":"Effect not found"}

    # Remove effect
    col.delete_one({"id": effect_id})

    # For each spell containing it, drop the id and recompute
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

    return {"status":"success","deleted":effect_id,"patch_text":"\n".join(lines) + "\n"}

# ---- Helpers for effect dedupe ----
def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def _effect_duplicate_groups() -> list[dict]:
    """Group effects by normalized (name, description)."""
    eff_col = get_col("effects")
    docs = list(eff_col.find({}, {"_id": 0, "id": 1, "name": 1, "description": 1}))
    buckets: dict[tuple[str,str], list[dict]] = {}
    for e in docs:
        key = (_norm_text(e.get("name")), _norm_text(e.get("description")))
        buckets.setdefault(key, []).append(e)
    groups = []
    for (n, d), items in buckets.items():
        if len(items) > 1:
            ids = sorted(str(x["id"]) for x in items)
            groups.append({
                "name":      items[0].get("name", ""),
                "description": items[0].get("description", ""),
                "ids":       ids,
                "keep":      ids[0],
                "remove":    ids[1:],
                "count":     len(ids),
            })
    return groups

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

        # Update spells referencing any of the remove_ids -> keep
        if remove_ids:
            affected = list(sp_col.find({"effects": {"$in": remove_ids}}, {"_id": 1, "id": 1, "effects": 1}))
            for sp in affected:
                old_list = [str(x) for x in (sp.get("effects") or [])]
                changed = False
                new_list = []
                seen = set()
                for eid in old_list:
                    if eid in remove_ids:
                        eid = keep  # remap to kept id
                        changed = True
                    # prevent duplicate entries
                    if eid not in seen:
                        new_list.append(eid)
                        seen.add(eid)
                if changed:
                    sp_col.update_one({"_id": sp["_id"]}, {"$set": {"effects": new_list}})
                    total_spells_touched += 1

        # Delete duplicates
        if remove_ids:
            r = eff_col.delete_many({"id": {"$in": remove_ids}})
            total_deleted += int(r.deleted_count or 0)

    return {
        "status":"success",
        "applied": True,
        "deleted_effects": total_deleted,
        "touched_spells": total_spells_touched,
        "groups": plan,
        "total_groups": len(plan),
        "message": f"Removed {total_deleted} duplicate effects; updated {total_spells_touched} spell(s)."
    }

# --- helper: how many MP until the next category threshold ---
def mp_to_next_category_delta(current_mp: int) -> int:
    """
    Smallest non-negative delta MP so that category_for_mp(current_mp + delta)
    is strictly higher than category_for_mp(current_mp).
    Returns 0 if already at the top tier (no higher category).
    """
    cur_cat = category_for_mp(int(current_mp or 0))

    # Exponential search to find an upper bound where category changes
    step = 1
    base = int(current_mp or 0)
    MAX_MP = base + 100_000  # sane cap
    hi = base + step
    while hi <= MAX_MP and category_for_mp(hi) == cur_cat:
        step *= 2
        hi = base + step
    if hi > MAX_MP:
        # couldn't find a higher category within cap -> treat as top category
        return 0

    # Binary search for first MP where category changes
    lo = max(base, hi - step)
    ans = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if category_for_mp(mid) == cur_cat:
            lo = mid + 1
        else:
            ans = mid
            hi = mid - 1

    if ans is None:
        return 0
    return max(0, ans - base)

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


def _recompute_spells_for_school(school_id: str) -> tuple[str, int]:
    """
    Recompute every spell that references ANY effect from this school.
    Returns (patch_text, changed_count).
    """
    eff_col = get_col("effects")
    sp_col  = get_col("spells")

    eff_ids = [e["id"] for e in eff_col.find({"school": school_id}, {"_id":0,"id":1})]
    if not eff_ids:
        return (f"No effects belong to school [{school_id}].", 0)

    affected = list(sp_col.find({"effects": {"$in": eff_ids}}, {"_id": 0}))
    if not affected:
        return ("No spells referenced effects from this school.", 0)

    changed = 0
    lines: list[str] = [f"Recompute after School update [{school_id}]:", ""]

    for sp in affected:
        old_mp = int(sp.get("mp_cost", 0))
        old_en = int(sp.get("en_cost", 0))
        old_cat = sp.get("category", "")

        cc = compute_spell_costs(
            sp.get("activation","Action"),
            int(sp.get("range",0)),
            sp.get("aoe","A Square"),
            int(sp.get("duration",1)),
            [str(x) for x in (sp.get("effects") or [])]
        )

        new_mp, new_en, new_cat = cc["mp_cost"], cc["en_cost"], cc["category"]

        if (old_mp, old_en, old_cat) != (new_mp, new_en, new_cat):
            sp_col.update_one({"id": sp["id"]}, {"$set": {
                "mp_cost": new_mp,
                "en_cost": new_en,
                "category": new_cat
            }})
            changed += 1
            lines.append(
              f"[{sp['id']}] {sp.get('name','(unnamed)')}: "
              f"MP {old_mp} → {new_mp}, EN {old_en} → {new_en}, Category {old_cat} → {new_cat}"
            )

    if changed == 0:
        lines.append("No MP/EN/category changes after recompute.")
    return ("\n".join(lines), changed)


@app.put("/admin/schools/{school_id}")
async def admin_update_school(school_id: str, request: Request):
    require_auth(request, ["admin", "moderator"])
    body = await request.json()

    sch = get_col("schools")
    old = sch.find_one({"id": school_id}, {"_id": 0})
    if not old:
        return JSONResponse({"status":"error","message":"School not found"}, status_code=404)

    # Only allow editing of these fields
    name        = (body.get("name") or old.get("name","")).strip()
    school_type = (body.get("school_type") or old.get("school_type","Simple")).strip()
    range_type  = (body.get("range_type")  or old.get("range_type","A")).strip().upper()
    aoe_type    = (body.get("aoe_type")    or old.get("aoe_type","A")).strip().upper()
    upgrade     = bool(body.get("upgrade", old.get("upgrade", old.get("is_upgrade", False))))

    sch.update_one({"id": school_id}, {"$set":{
        "name": name,
        "school_type": school_type,
        "range_type": range_type,
        "aoe_type": aoe_type,
        "upgrade": bool(upgrade)
    }})

    # build header of changes
    ch = []
    def _chg(lbl, a, b):
        if a != b: ch.append(f"{lbl}: {a} → {b}")
    _chg("Name", old.get("name",""), name)
    _chg("Type", old.get("school_type",""), school_type)
    _chg("Range Type", old.get("range_type",""), range_type)
    _chg("AoE Type", old.get("aoe_type",""), aoe_type)
    _chg("Upgrade", bool(old.get("upgrade", old.get("is_upgrade", False))), bool(upgrade))

    header = [f"Edited School [{school_id}] {name}", ""]
    header.extend(ch if ch else ["No direct field changes"])
    header.append("")

    patch_text, changed_count = _recompute_spells_for_school(school_id)
    return {"status":"success","updated":school_id,"changed_spells":changed_count,"patch_text":"\n".join(header)+patch_text+"\n"}


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

    # If force=True, delete all its effects as well and recompute spells
    lines = [f"Deleted School [{school_id}] {school.get('name','')}",""]
    if used_count > 0 and force:
        # gather effect IDs before deletion
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

    sch.delete_one({"id": school_id})
    return {"status":"success","deleted":school_id,"patch_text":"\n".join(lines) + "\n"}

# ========================= Apotheosis 
def compute_apotheosis_stats(
    characteristic_value: int,
    stage: str,
    apo_type: str,
    constraint_ids: list[str],
    trade_p2s_steps: int = 0,
    trade_p2a_steps: int = 0,
    trade_s2a_steps: int = 0,
) -> dict:

    col = get_col("apotheosis_constraints")
    docs = list(col.find({"id": {"$in": [str(x) for x in (constraint_ids or [])]}}))

    total_difficulty = sum(int(d.get("difficulty", 0)) for d in docs)

    stability = apo_stage_stability(stage)
    power     = int(characteristic_value or 0) + total_difficulty
    amplitude = 0

    tbonus = apo_type_bonus(apo_type)
    power     += tbonus.get("power", 0)
    stability += tbonus.get("stability", 0)
    amplitude += tbonus.get("amplitude", 0)

    for d in docs:
        stability += int(d.get("stability_delta", 0))
        if bool(d.get("forbid_p2s", False)):
            forbid_p2s = True

    p2s_applied = 0
    if not forbid_p2s and trade_p2s_steps > 0:
        for _ in range(int(trade_p2s_steps)):
            if power >= P2S_COST:
                power -= P2S_COST
                stability += P2S_GAIN
                p2s_applied += 1
            else:
                break

    p2a_applied = 0
    if trade_p2a_steps > 0:
        for _ in range(int(trade_p2a_steps)):
            if power >= P2A_COST:
                power -= P2A_COST
                amplitude += 1
                p2a_applied += 1
            else:
                break

    s2a_applied = 0
    if trade_s2a_steps > 0:
        for _ in range(int(trade_s2a_steps)):
            if stability >= S2A_COST:
                stability -= S2A_COST
                amplitude += 1
                s2a_applied += 1
            else:
                break

    diameter = 17 + 2 * max(0, int(amplitude))

    return {
        "stability": max(0, int(stability)),
        "power": max(0, int(power)),
        "amplitude": max(0, int(amplitude)),
        "diameter": int(diameter),
        "total_difficulty": int(total_difficulty),
        "tier": tier_from_total_difficulty(total_difficulty),
        "flags": {"forbid_p2s": forbid_p2s, "p2s_applied": p2s_applied, "p2a_applied": p2a_applied, "s2a_applied": s2a_applied}
    }

# ---------- Apotheosis: constraints (list / parse / CRUD) ----------
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
    require_auth(request, roles=["moderator","admin"])
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

# ---------- Apotheosis: compute (live preview) ----------
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

# ---------- Apotheoses (create/browse/favorite) ----------
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
def list_apotheoses(request: Request, name: str | None = Query(default=None), typ: str | None = Query(default=None), stage: str | None = Query(default=None), favorite: str | None = Query(default=None)):
    # auth optional; favorites requires auth
    qp = request.query_params
    q = {}
    if name:  q["name"]  = {"$regex": name, "$options": "i"}
    if typ:   q["type"]  = {"$regex": typ, "$options": "i"}
    if stage: q["stage"] = {"$regex": stage, "$options": "i"}

    fav_only = str(favorite or "").lower() in ("1","true","yes")
    if fav_only:
        user, _ = require_user_doc(request)
        fav = [str(x) for x in (user.get("fav_apotheoses") or [])]
        if not fav:
            return {"status":"success","apotheoses":[]}
        q["id"] = {"$in": fav}

    docs = list(get_col("apotheoses").find(q, {"_id":0}))
    docs.sort(key=lambda d: d["name"].lower())
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


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
