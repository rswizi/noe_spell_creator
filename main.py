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
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import DuplicateKeyError

from db_mongo import get_col, next_id_str, get_db, ensure_indexes, sync_counters

# Domain imports
from server.src.objects.effects import load_effect
from server.src.objects.spells import Spell
from server.src.modules.category_table import category_for_mp


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

def compute_spell_costs(
    activation: str, range_val: int, aoe: str, duration: int, effect_ids: list[str]
) -> dict:
    """Load effects and compute MP/EN with your Spell model."""
    try:
        effects = [load_effect(str(eid)) for eid in (effect_ids or [])]
    except Exception:
        # fallback stub if load_effect ever fails
        docs = list(get_col("effects").find(
            {"id": {"$in": [str(eid) for eid in (effect_ids or [])]}},
            {"_id": 0, "mp_cost": 1, "en_cost": 1}
        ))
        class _E:
            def __init__(self, mp, en):
                self.mp_cost = int(mp or 0)
                self.en_cost = int(en or 0)
        effects = [_E(d.get("mp_cost", 0), d.get("en_cost", 0)) for d in docs]

    mp_cost, en_cost = Spell.compute_cost(range_val, aoe, duration, activation, effects)
    return {"mp_cost": mp_cost, "en_cost": en_cost, "category": category_for_mp(mp_cost)}


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
ALLOWED_PAGES = {"home", "index", "scraper", "templates", "admin", "export"}


# ---------- Pages ----------
@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/home.html")

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
async def bulk_create_effects(request: Request):
    """Admin: create a batch of effects for a school."""
    try:
        require_auth(request, ["admin"])
        body = await request.json()

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

        existing = sch_col.find_one({"name": {"$regex": f"^{re.escape(school_name)}$", "$options": "i"}}, {"_id": 0})
        if existing:
            sid = existing["id"]
            sch_col.update_one(
                {"id": sid},
                {"$set": {"school_type": school_type, "range_type": range_type, "aoe_type": aoe_type, "upgrade": bool(upgrade)}}
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
            try:
                mp   = int(e.get("mp_cost"))
                en   = int(e.get("en_cost"))
            except Exception:
                return JSONResponse({"status":"error","message":f"Non-numeric MP/EN in effect '{name}'"}, status_code=400)

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
    body = await request.json()
    range_val     = body.get("range")
    aoe_val       = body.get("aoe")
    duration_val  = body.get("duration")
    activation_val= body.get("activation")
    effect_ids    = [str(e) for e in (body.get("effects") or []) if str(e).strip()]

    effects = [load_effect(eid) for eid in effect_ids]
    mp_cost, en_cost = Spell.compute_cost(range_val, aoe_val, duration_val, activation_val, effects)
    category = category_for_mp(mp_cost)
    return {"mp_cost": mp_cost, "en_cost": en_cost, "category": category}

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
        aoe_val     = body.get("aoe") or "A Square"
        try:
            duration  = int(body.get("duration", 1))
        except Exception:
            return JSONResponse({"status": "error", "message": "duration must be an integer"}, status_code=400)

        effect_ids = [str(e).strip() for e in (body.get("effects") or []) if str(e).strip()]
        if not effect_ids:
            return JSONResponse({"status": "error", "message": "At least one effect is required."}, status_code=400)

        missing = [eid for eid in effect_ids if not get_col("effects").find_one({"id": eid}, {"_id": 1})]
        if missing:
            return JSONResponse({"status": "error", "message": f"Unknown effect id(s): {', '.join(missing)}"}, status_code=400)

        cc = compute_spell_costs(activation, range_val, aoe_val, duration, effect_ids)

        doc = {
            "id": next_id_str("spells", padding=4),
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
        }

        get_col("spells").insert_one(dict(doc))

        return {"status": "success", "id": doc["id"], "spell": doc}

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

# ---------- Ops ----------
@app.get("/health")
def health():
    try:
        get_db().list_collection_names()
        return {"status": "ok", "mongo": "connected"}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
