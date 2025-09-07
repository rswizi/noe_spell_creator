import datetime
import re
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import DuplicateKeyError
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from db_mongo import get_col, next_id_str, get_db, ensure_indexes, sync_counters, norm_key, spell_sig

from server.src.modules.apotheosis_helpers import compute_apotheosis_stats, _can_edit_apotheosis
from server.src.modules.authentification_helpers import _ALLOWED_ROLES, SESSIONS, find_user, require_auth, make_token, verify_password, get_auth_token, normalize_email,_sha256
from server.src.modules.logging_helpers import logger, write_audit
from server.src.modules.spell_helpers import compute_spell_costs, _effect_duplicate_groups, _recompute_spells_for_school, _recompute_spells_for_effect
from wiki_router import router as wiki_router
import os

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
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

app.include_router(wiki_router, prefix="/api")

if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

templates = Jinja2Templates(directory=TEMPLATES_DIR)

# --- Portal Wiki pages ---
@app.get("/portal/wiki", response_class=HTMLResponse)
def portal_wiki_home(request: Request):
    return templates.TemplateResponse("wiki.html", {"request": request})

@app.get("/portal/wiki/{slug}", response_class=HTMLResponse)
def portal_wiki_page(request: Request, slug: str):
    # `slug` is used by wiki.js via window.__WIKI_SLUG (see template below)
    return templates.TemplateResponse("wiki_page.html", {"request": request, "slug": slug})

# ---------- Pages ----------
app.mount("/static", StaticFiles(directory=str(CLIENT_DIR)), name="static")

ALLOWED_PAGES = {"home", "index", "scraper", "templates", "admin", "export", "user_management","signup","browse","browse_effects","browse_schools","portal","apotheosis_home","apotheosis_create","apotheosis_browse","apotheosis_parse_constraints","apotheosis_constraints","spell_list_home","spell_list_view","wiki"}

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
            "linked_skill": s.get("linked_skill"),
            "linked_intensities": s.get("linked_intensities", []),
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
            try:
                mp   = int(e.get("mp_cost"))
                en   = int(e.get("en_cost"))
            except Exception:
                return JSONResponse({"status":"error","message":f"Non-numeric MP/EN in effect '{name}'"}, status_code=400)

            dup = eff_col.find_one(
                {"school": school["id"], "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}, "mp_cost": mp, "en_cost": en},
                {"_id": 1}
            )
            if dup:
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
            return {"spells": [], "page": page, "limit": limit, "total": 0, "error": he.detail}
        fav_ids = [str(x) for x in (user.get("favorites") or [])]
        if not fav_ids:
            return {"spells": [], "page": page, "limit": limit, "total": 0}
        q["id"] = {"$in": fav_ids}

    total = sp_col.count_documents(q)
    cursor = sp_col.find(q, {"_id": 0}).skip((page - 1) * limit).limit(limit)
    spells = list(cursor)

    school_map = {s["id"]: s.get("name", s["id"]) for s in sch_col.find({}, {"_id": 0, "id": 1, "name": 1})}

    all_eff_ids = {str(eid) for sp in spells for eid in (sp.get("effects") or [])}
    eff_docs = list(eff_col.find({"id": {"$in": list(all_eff_ids)}}, {"_id": 0, "id": 1, "school": 1}))
    eff_school = {d["id"]: str(d.get("school") or "") for d in eff_docs}

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

        missing = [eid for eid in effect_ids if not get_col("effects").find_one({"id": eid}, {"_id": 1})]
        if missing:
            return JSONResponse({"status": "error", "message": f"Unknown effect id(s): {', '.join(missing)}"}, status_code=400)

        cc = compute_spell_costs(activation, range_val, aoe_val, duration, effect_ids)

        sig = spell_sig(activation, range_val, aoe_val, duration, effect_ids)

        conflict = get_col("spells").find_one({"sig_v1": sig}, {"_id": 0, "id": 1, "name": 1})
        if conflict:
            return JSONResponse(
                {
                    "status": "error",
                    "message": f"Another spell with identical parameters already exists (id {conflict.get('id')}, name '{conflict.get('name','')}')."
                },
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
            "mp_cost": cc["mp_cost"],
            "en_cost": cc["en_cost"],
            "category": cc["category"],
            "spell_type": body.get("spell_type") or "Simple",
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

    col.update_one({"id": effect_id}, {"$set": {
        "name": name, "description": desc, "mp_cost": mp, "en_cost": en, "school": school
    }})

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
def list_apotheoses(request: Request, name: str | None = Query(default=None), typ: str | None = Query(default=None), stage: str | None = Query(default=None), favorite: str | None = Query(default=None)):
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
    username, role = require_auth(request, roles=["user","moderator","admin"])
    doc = get_col("spell_lists").find_one({"id": list_id}, {"_id":0})
    if not _can_access_list(doc, username, role):
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

@app.get("/spell_lists/{list_id}/spells")
def spell_list_spells(list_id: str, request: Request):
    username, role = require_auth(request, roles=["user","moderator","admin"])
    sl = get_col("spell_lists").find_one({"id": list_id}, {"_id":0})
    if not _can_access_list(sl, username, role):
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
    eff_docs = list(eff_col.find({"id": {"$in": list(all_eff_ids)}}, {"_id":0,"id":1,"school":1}))
    eff_school = {d["id"]: str(d.get("school") or "") for d in eff_docs}
    out = []
    for sp in spells:
        sch_ids = sorted({eff_school.get(str(eid), "") for eid in (sp.get("effects") or []) if eff_school.get(str(eid), "")})
        sp["schools"] = [{"id": sid, "name": school_map.get(sid, sid)} for sid in sch_ids]
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

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)