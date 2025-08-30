import os
import json
import uvicorn
import logging
import secrets
import datetime
import json
import re
import hashlib
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from typing import Dict, Tuple, Optional
from db_mongo import get_col, next_id_str, get_db, ensure_indexes, sync_counters
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import re



from server.src.objects.effects import load_effect
from server.src.objects.spells import Spell, load_spell
from server.src.objects.schools import load_school
from server.src.modules.category_table import category_for_mp

ensure_indexes()
sync_counters()
logger = logging.getLogger("noe")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler("server.log", encoding="utf-8"), logging.StreamHandler()]
)

# Create app instance
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

USERS_COL = "users"

def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def find_user(username: str) -> dict | None:
    return get_col("users").find_one({"username": username}, {"_id": 0})

def verify_password(input_pw: str, user_doc: dict) -> bool:
    # accept plaintext ('password') or sha256 hash ('password_hash')
    return (
        user_doc.get("password") == input_pw
        or user_doc.get("password_hash") == _sha256(input_pw)
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- STARTUP ----
    ensure_indexes()

    # one-time seed of admin (only if missing and env vars provided)
    u = os.getenv("ADMIN_USER")
    p = os.getenv("ADMIN_PASSWORD")
    if u and p:
        col = get_col("users")
        if not col.find_one({"username": u}):
            col.update_one(
                {"username": u},
                {"$set": {"username": u, "password_hash": _sha256(p), "role": "admin"}},
                upsert=True,
            )
            logger.info("Seeded admin user '%s' from env", u)

    yield


# --- cost wrapper used by PUT /spells ---
def compute_spell_costs(activation: str, range_val: int, aoe: str, duration: int, effect_ids: list[str]) -> dict:
    effects = [load_effect(str(e)) for e in (effect_ids or [])]
    mp_cost, en_cost = Spell.compute_cost(range_val, aoe, duration, activation, effects)
    return {"mp_cost": mp_cost, "en_cost": en_cost, "category": category_for_mp(mp_cost)}

logger = logging.getLogger("noe")

BASE_DIR = Path(__file__).parent
USERS_FILE = BASE_DIR / "server" / "data" / "users.txt"

def migrate_users_txt_to_mongo():
    col = get_col("users")
    try:
        # unique index (idempotent)
        get_col("users").create_index("username", unique=True)
    except Exception:
        pass

    if not USERS_FILE.exists():
        logger.info("users.txt not found; skipping import (Mongo users only).")
        return

    count = 0
    with USERS_FILE.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue
            username = parts[0]
            password = parts[1]
            role = parts[2] if len(parts) > 2 else "user"

            if not col.find_one({"username": username}):
                col.insert_one({"username": username, "password": password, "role": role})
                count += 1
    logger.info("Imported %d user(s) from users.txt into Mongo.", count)

migrate_users_txt_to_mongo()

SESSIONS: Dict[str, Tuple[str, str]] = {}  # token -> (username, role)

def make_token() -> str:
    return secrets.token_hex(16)

def get_auth_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None

def serialize_spell(spell: Spell) -> dict:
    """Return a JSON-serializable spell (effects as ids)."""
    d = spell.to_dict()
    return d

def get_next_spell_id() -> str:
    return next_id_str("spells", padding=4)

def require_auth(request: Request, roles: Optional[list[str]] = None) -> Tuple[str, str]:
    """Return (username, role) or raise Exception."""
    token = request.headers.get("Authorization", "")
    if token.lower().startswith("bearer "):
        token = token.split(" ", 1)[1].strip()
    if not token or token not in SESSIONS:
        raise Exception("Not authenticated")
    username, role = SESSIONS[token]
    if roles and role not in roles:
        raise Exception("Forbidden")
    return username, role

def write_audit(action, username, spell_id, before, after):
    get_col("audit_logs").insert_one({
        "ts": datetime.datetime.utcnow().isoformat()+"Z",
        "user": username, "action": action, "spell_id": spell_id,
        "before": before, "after": after
    })

# --- ID helpers ---
def get_next_effect_id() -> str:
    return next_id_str("effects", padding=4)

def get_next_school_id() -> str:
    return next_id_str("schools", padding=4)

def find_school_by_name_mongo(name: str) -> dict | None:
    col = get_col("schools")
    return col.find_one({"name": {"$regex": f"^{re.escape(name.strip())}$", "$options": "i"}},
                        {"_id": 0})

def ensure_school_mongo(name: str, school_type: str,
                        range_type: str, aoe_type: str, upgrade: bool) -> dict:
    
    col = get_col("schools")
    existing = find_school_by_name_mongo(name)
    if existing:
        updates = {
            "school_type": school_type,
            "range_type": range_type,
            "aoe_type": aoe_type,
            "upgrade": bool(upgrade),
        }
        col.update_one({"id": existing["id"]}, {"$set": updates})
        existing.update(updates)
        return existing

    sid = next_id_str("schools")
    doc = {
        "id": sid,
        "name": name.strip(),
        "school_type": school_type,
        "range_type": range_type,
        "aoe_type": aoe_type,
        "upgrade": bool(upgrade),
    }
    col.insert_one(doc)
    return doc

# --- BULK CREATE EFFECTS (admin only) ---
from fastapi import HTTPException

@app.on_event("startup")
def on_startup():
    ensure_indexes()

    # one-time seed of admin if missing (using env vars)
    u = os.getenv("ADMIN_USER")
    p = os.getenv("ADMIN_PASSWORD")
    if u and p:
        if not get_col("users").find_one({"username": u}):
            get_col("users").update_one(
                {"username": u},
                {"$set": {"username": u, "password_hash": _sha256(p), "role": "admin"}},
                upsert=True,
            )
            logger.info("Seeded admin user '%s' from env", u)

@app.post("/effects/bulk_create")
async def bulk_create_effects(request: Request):
    try:
        existing = sch_col.find_one({"name": {"$regex": f"^{re.escape(school_name)}$", "$options": "i"}})
        username, role = require_auth(request, ["admin"])
        body = await request.json()

        school_name = (body.get("school_name") or "").strip()
        school_type = (body.get("school_type") or "Simple").strip()
        range_type  = (body.get("range_type")  or "A").strip()
        aoe_type    = (body.get("aoe_type")    or "A").strip()
        upgrade     = bool(body.get("upgrade", body.get("is_upgrade", False)))
        effects     = body.get("effects") or []
        if not school_name:
            raise HTTPException(status_code=400, detail="school_name is required")
        if not effects:
            raise HTTPException(status_code=400, detail="effects must be a non-empty list")

        sch_col = get_col("schools")
        eff_col = get_col("effects")

        # ensure / upsert school by name
        existing = sch_col.find_one({"name": {"$regex": f"^{school_name}$", "$options": "i"}})
        if existing:
            sid = existing["id"]
            sch_col.update_one(
                {"id": sid},
                {"$set": {"school_type": school_type, "range_type": range_type, "aoe_type": aoe_type, "upgrade": bool(upgrade)}}
            )
            school = sch_col.find_one({"id": sid}, {"_id": 0})
        else:
            sid = get_next_school_id()
            school = {
                "id": sid, "name": school_name, "school_type": school_type,
                "upgrade": bool(upgrade), "range_type": range_type, "aoe_type": aoe_type
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
                raise HTTPException(status_code=400, detail=f"Non-numeric MP/EN in effect '{name}'")

            eff_id = get_next_effect_id()
            rec = {"id": eff_id, "name": name, "description": desc, "mp_cost": mp, "en_cost": en, "school": school["id"]}
            eff_col.insert_one(rec)
            created.append(eff_id)

        write_audit("bulk_create_effects", username, spell_id="—", before=None,
                    after={"school": school, "range_type": range_type, "aoe_type": aoe_type, "upgrade": upgrade, "created": created})
        return {"status": "success", "school": school, "created": created}
    except HTTPException as he:
        return {"status": "error", "message": he.detail}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/", include_in_schema=False)
def serve_home():
    return FileResponse(CLIENT_DIR / "home.html")

@app.get("/effects")
def get_effects(name: str | None = Query(default=None), school: str | None = Query(default=None)):
    col = get_col("effects")
    sch_col = get_col("schools")

    q = {}
    if name:
        # case-insensitive substring match
        q["name"] = {"$regex": name, "$options": "i"}
    if school:
        # accept id or school name via lookup
        # try by id first
        or_terms = [{"school": {"$regex": school, "$options": "i"}}]
        # also match by school name → find matching school ids
        ids = [s["id"] for s in sch_col.find({"name": {"$regex": school, "$options": "i"}}, {"id": 1})]
        if ids:
            or_terms.append({"school": {"$in": ids}})
        q["$or"] = or_terms

    docs = list(col.find(q, {"_id": 0}))
    # Attach school_name to match your UI convenience
    school_map = {s["id"]: s.get("name", s["id"]) for s in sch_col.find({}, {"_id": 0, "id": 1, "name": 1})}
    for e in docs:
        sid = str(e.get("school") or "")
        e["school_name"] = school_map.get(sid, sid)
    return {"effects": docs}

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

@app.get("/schools")
def list_schools():
    try:
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
    except Exception as e:
        return {"error": str(e)}

@app.get("/spells", summary="List spells (resilient to funky query params)")
def list_spells(request: Request):
    # raw, resilient params (avoid pydantic 422 on empty/undefined strings)
    qp = request.query_params
    name = qp.get("name") or None
    category = qp.get("category") or None
    school = qp.get("school") or None

    try:
        page = int(qp.get("page") or 1)
    except Exception:
        page = 1
    try:
        limit = int(qp.get("limit") or 100)
    except Exception:
        limit = 100
    page = max(1, page)
    limit = max(1, min(500, limit))

    sp_col  = get_col("spells")
    eff_col = get_col("effects")
    sch_col = get_col("schools")

    # base filter
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

    # get all effect -> school in one shot
    all_eff_ids = {str(eid) for sp in spells for eid in (sp.get("effects") or [])}
    eff_docs = list(eff_col.find({"id": {"$in": list(all_eff_ids)}}, {"_id": 0, "id": 1, "school": 1}))
    eff_school = {d["id"]: str(d.get("school") or "") for d in eff_docs}

    # attach derived schools to each spell
    out = []
    for sp in spells:
        sch_ids = sorted({eff_school.get(str(eid), "") for eid in (sp.get("effects") or []) if eff_school.get(str(eid), "")})
        sp["schools"] = [{"id": sid, "name": school_map.get(sid, sid)} for sid in sch_ids]
        out.append(sp)

    # post-filter by school (accept id or name, case-insensitive)
    if school:
        s_low = school.lower()
        out = [
            sp for sp in out
            if any(s["id"].lower() == s_low or s["name"].lower() == s_low for s in sp["schools"])
        ]

    return {"spells": out, "page": page, "limit": limit, "total": total}


# fetch one spell
@app.get("/spells/{spell_id}")
def get_spell(spell_id: str):
    doc = get_col("spells").find_one({"id": spell_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, f"Spell {spell_id} not found")
    return {"spell": doc}

# update/overwrite a spell
@app.put("/spells/{spell_id}")
async def update_spell(spell_id: str, request: Request):
    """
    Update an existing spell. Returns clear JSON on any error so the UI
    never shows a generic 'Unknown error'.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"status": "error", "message": "Invalid JSON body"},
            status_code=400,
        )

    try:
        name        = (body.get("name") or "Unnamed Spell").strip()
        activation  = body.get("activation") or "Action"
        # coerce types but keep originals for error messages
        try:
            range_val = int(body.get("range", 0))
        except Exception:
            return JSONResponse({"status":"error","message":"range must be an integer"}, status_code=400)

        aoe_val     = body.get("aoe") or "A Square"
        try:
            duration  = int(body.get("duration", 1))
        except Exception:
            return JSONResponse({"status":"error","message":"duration must be an integer"}, status_code=400)

        effect_ids_raw = body.get("effects") or []
        effect_ids     = [str(e).strip() for e in effect_ids_raw if str(e).strip()]

        # make sure all effects exist so we don’t 500 later
        missing = []
        for eid in effect_ids:
            if not get_col("effects").find_one({"id": eid}, {"_id": 0}):
                missing.append(eid)
        if missing:
            return JSONResponse(
                {"status": "error", "message": f"Unknown effect id(s): {', '.join(missing)}"},
                status_code=400,
            )

        # compute costs/category using your model/utilities
        cc = compute_spell_costs(activation, range_val, aoe_val, duration, effect_ids)

        doc = {
            "name": name,
            "activation": activation,
            "range": range_val,
            "aoe": aoe_val,
            "duration": duration,
            "effects": effect_ids,           # IDs only (builder expects this)
            "mp_cost": cc["mp_cost"],
            "en_cost": cc["en_cost"],
            "category": cc["category"],
        }

        r = get_col("spells").update_one({"id": spell_id}, {"$set": doc}, upsert=False)
        if r.matched_count == 0:
            return JSONResponse(
                {"status": "error", "message": f"Spell {spell_id} not found"},
                status_code=404,
            )

        return {"status": "success", "id": spell_id, "spell": doc}

    except Exception as e:
        # log full stack server-side but return a readable message to UI
        import traceback, logging
        logging.getLogger("noe").exception("PUT /spells/%s failed", spell_id)
        return JSONResponse(
            {"status": "error", "message": f"{type(e).__name__}: {e}"},
            status_code=500,
        )

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

@app.delete("/spells/{spell_id}")
def delete_spell(spell_id: str, request: Request):
    try:
        username, role = require_auth(request, ["admin","moderator"])
        get_col("spells").delete_one({"id": spell_id})
        return {"status":"success","deleted": spell_id}
    except Exception as e:
        return {"status":"error","message": str(e)}

@app.post("/submit_spell")
async def submit_spell(request: Request):
    try:
        body = await request.json()

        name        = (body.get("name") or "Unnamed Spell").strip()
        activation  = body.get("activation") or "Action"
        aoe_val     = body.get("aoe") or "A Square"
        try:
            range_val = int(body.get("range") or 0)
        except:
            return JSONResponse({"status": "error", "message": "range must be an integer"}, status_code=400)
        try:
            duration  = int(body.get("duration") or 1)
        except:
            return JSONResponse({"status": "error", "message": "duration must be an integer"}, status_code=400)

        effect_ids = [str(e).strip() for e in (body.get("effects") or []) if str(e).strip()]
        if not effect_ids:
            return JSONResponse({"status": "error", "message": "At least one effect is required"}, status_code=400)

        # Validate effects exist
        eff_col = get_col("effects")
        missing = [e for e in effect_ids if not eff_col.find_one({"id": e}, {"_id": 0})]
        if missing:
            return JSONResponse({"status": "error", "message": f"Unknown effect id(s): {', '.join(missing)}"}, status_code=400)

        # Compute costs & category
        cc = compute_spell_costs(activation, range_val, aoe_val, duration, effect_ids)

        sid = next_id_str("spells", padding=4)
        doc = {
            "id": sid,
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
            "description": body.get("description") or "",
        }

        get_col("spells").insert_one(doc)
        return {"status": "success", "id": sid, "spell": doc}

    except Exception as e:
        logger.exception("submit_spell failed")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/home.html")


BASE_DIR = Path(__file__).resolve().parent
CLIENT_DIR = BASE_DIR / "client"
app.mount("/static", StaticFiles(directory=str(CLIENT_DIR)), name="static")

def serve_home():
    return FileResponse(CLIENT_DIR / "home.html")

ALLOWED_PAGES = {"home", "index", "scraper", "templates", "admin", "export"}

@app.get("/{page}.html", include_in_schema=False)
def serve_page(page: str):
    if page in ALLOWED_PAGES:
        return FileResponse(CLIENT_DIR / f"{page}.html")
    raise HTTPException(404, "Page not found")

@app.get("/health")
def health():
    try:
        db = get_db()
        # a cheap call that touches the DB
        db.list_collection_names()
        return {"status": "ok", "mongo": "connected"}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)