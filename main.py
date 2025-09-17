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

from db_mongo import get_col, next_id_str, get_db, ensure_indexes, sync_counters, norm_key, spell_sig

from server.src.modules.apotheosis_helpers import compute_apotheosis_stats, _can_edit_apotheosis
from server.src.modules.authentification_helpers import _ALLOWED_ROLES, SESSIONS, find_user, require_auth, make_token, verify_password, get_auth_token, normalize_email,_sha256
from server.src.modules.logging_helpers import logger, write_audit
from server.src.modules.spell_helpers import compute_spell_costs, _effect_duplicate_groups, _recompute_spells_for_school, _recompute_spells_for_effect, recompute_all_spells
from server.src.modules.objects_helpers import _object_from_body
from server.src.modules.inventory_helpers import WEAPON_UPGRADES, ARMOR_UPGRADES, _slots_for_quality, _upgrade_fee_for_range, _qprice, _compose_variant, _pick_currency, QUALITY_ORDER

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

# ---------- Pages ----------
app.mount("/static", StaticFiles(directory=str(CLIENT_DIR)), name="static")

ALLOWED_PAGES = {"home", "index", "scraper", "templates", "admin", "export", "user_management","signup","browse","browse_effects","browse_schools","portal","apotheosis_home","apotheosis_create","apotheosis_browse","apotheosis_parse_constraints","apotheosis_constraints","spell_list_home","spell_list_view", "inventory_home", "inventory_manage", "objects_home", "objects_parse", "objects_edit", "tools_home", "tools_parse", "tools_edit", "weapons_home", "weapons_parse", "weapons_edit","equipment_home","equipment_parse","equipement_edit","inventory_browse","inventory_create","inventory_view",}

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
                            "school": school["id"]
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
            rec = {"id": eff_id, "name": name, "description": desc, "mp_cost": mp, "en_cost": en, "school": school["id"]}
            eff_col.insert_one(rec)
            created.append(eff_id)

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

        raw_effects = [str(e).strip() for e in (body.get("effects") or []) if str(e).strip()]

        effect_ids = []
        seen = set()
        for eid in raw_effects:
            if eid not in seen:
                seen.add(eid)
                effect_ids.append(eid)
                
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

        raw_effects = [str(e).strip() for e in (body.get("effects") or []) if str(e).strip()]

        effect_ids = []
        seen = set()
        for eid in raw_effects:
            if eid not in seen:
                seen.add(eid)
                effect_ids.append(eid)
    
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
    # creator must be moderator/admin
    username, role = require_auth(request, roles=["moderator","admin"])
    col = get_col("objects")
    doc = _object_from_body(body)
    doc["id"] = next_id_str("objects", padding=4)
    doc["created_at"] = datetime.datetime.utcnow().isoformat() + "Z"
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
    out = {
        "name": name,
        "name_key": norm_key(name),
        "tier": str(tier),
        "enc": enc,
        "method": method,
        "description": desc,
    }
    out.update(_derive_for(method, tier))
    return out

@app.get("/tools")
def list_tools(q: str | None = Query(None)):
    col = get_col("tools")
    filt = {}
    if q: filt["name_key"] = {"$regex": norm_key(q)}
    return {"status":"success","tools": list(col.find(filt, {"_id":0}))}

@app.post("/tools")
def create_tool(request: Request, body: dict = Body(...)):
    require_auth(request, roles=["moderator","admin"])
    col = get_col("tools")
    doc = _tool_from_body(body)
    # duplicate protection by name_key
    if col.find_one({"name_key": doc["name_key"]}):
        raise HTTPException(status_code=409, detail="Tool with same name already exists")
    doc["id"] = next_id_str("tools", padding=4)
    doc["created_at"] = datetime.datetime.utcnow().isoformat()+"Z"
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
    username, role = require_auth(request, roles=["user","moderator","admin"])
    col = get_col("spell_lists")
    doc = col.find_one({"id": list_id}, {"_id":0})
    if not _can_access_list(doc, username, role):
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

def _weapon_from_body(b: dict) -> dict:
    name  = (b.get("name") or "").strip() or "Unnamed"
    skill = (b.get("skill") or "Technicity").strip().title()
    desc  = (b.get("description") or "").strip()
    dmg   = (b.get("damage") or "").strip()
    rng   = str(b.get("range") or "").strip()
    hands = int(b.get("hands") or 1)
    price = int(b.get("price") or 0)
    enc   = float(b.get("enc") or 0)
    fx    = _as_list(b.get("effects"))

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
        "is_animarma": bool(b.get("is_animarma") or False),
        "nature": (b.get("nature") or "").strip(),  # optional, can be edited later
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
    require_auth(request, roles=["moderator","admin"])
    col = get_col("weapons")

    base = _weapon_from_body(body)
    if col.find_one({"name_key": base["name_key"]}):
        raise HTTPException(status_code=409, detail="Weapon with same name already exists")

    base["id"] = next_id_str("weapons", padding=4)
    now = datetime.datetime.utcnow().isoformat()+"Z"
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
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="items must be a non-empty list")

    col = get_col("weapons")
    created, skipped = [], []
    now = datetime.datetime.utcnow().isoformat()+"Z"

    for b in items:
        base = _weapon_from_body({**b, "skill": skill, "is_animarma": False})
        if col.find_one({"name_key": base["name_key"]}):
            skipped.append(base["name"]); continue

        base["id"] = next_id_str("weapons", padding=4)
        base["created_at"] = now
        col.insert_one(dict(base))
        created.append({k:v for k,v in base.items() if k!="_id"})

        # auto-create animarma twin
        anim = _make_animarma(base)
        if not col.find_one({"name_key": anim["name_key"]}):
            anim["id"] = next_id_str("weapons", padding=4)
            anim["created_at"] = now
            col.insert_one(dict(anim))
            created.append({k:v for k,v in anim.items() if k!="_id"})

    return {"status":"success","created": created, "skipped": skipped}

# ---------- Equipment ----------
from fastapi import Body

def _eq_norm_name(name: str, fallback: str = "Unnamed") -> tuple[str, str]:
    nm = (name or "").strip() or fallback
    return nm, norm_key(nm)

def _equipment_from_body(b: dict) -> dict:
    cat = (b.get("category") or "").strip().lower()
    if cat not in ("special","slot","armor"):
        raise HTTPException(status_code=400, detail="category must be special | slot | armor")

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
            "price": int(b.get("price") or 0),
            "enc": float(b.get("enc") or 0),
        }
        return doc

    if cat == "slot":
        slot = (b.get("slot") or "head").strip().lower()
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
        }
        return doc

    # armor
    tname, key = _eq_norm_name(b.get("type"), "Armor")
    doc = {
        "category":"armor",
        "type": tname,
        "name": f"armor:{tname}", "name_key": norm_key(f"armor:{tname}"),
        "enc": float(b.get("enc") or 0),
        "receptacle": (b.get("receptacle") or "").strip(),
        "hp_bonus": int(b.get("hp_bonus") or 0),
        "effect": (b.get("effect") or "").strip(),
        "mo_penalty": int(b.get("mo_penalty") or 0),
        "price": int(b.get("price") or 2528),
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
    require_auth(request, roles=["moderator","admin"])
    col = get_col("equipment")
    doc = _equipment_from_body(body)
    if col.find_one({"category": doc["category"], "name_key": doc["name_key"]}):
        raise HTTPException(status_code=409, detail="Duplicate equipment")
    doc["id"] = next_id_str("equipment", padding=4)
    doc["created_at"] = datetime.datetime.utcnow().isoformat()+"Z"
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

# ---------- Inventories ----------
from fastapi import Body

def _new_container(name: str) -> dict:
    return {
        "id": next_id_str("container", padding=3),
        "name": (name or "Container").strip(),
        "include": True,        # counts into inventory.enc_total?
        "enc_total": 0.0        # running encumbrance stored in this container
    }

@app.post("/inventories")
def create_inventory(request: Request, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    name = (payload.get("name") or "Inventory").strip()
    currencies = payload.get("currencies") or {}
    containers = payload.get("containers") or []
    containers = [_new_container(c.get("name")) for c in containers] or [_new_container("Backpack")]
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
    invs = list(db.inventories.find({"owner": user}, {"_id":0}))
    return {"status":"success","inventories": invs}

@app.get("/inventories/{inv_id}")
def read_inventory(request: Request, inv_id: str):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user}, {"_id":0})
    if not inv: raise HTTPException(404, "Not found")
    return {"status":"success","inventory": inv}

@app.post("/inventories/{inv_id}/containers")
def add_container(request: Request, inv_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv: raise HTTPException(404, "Not found")
    c = _new_container(payload.get("name"))
    db.inventories.update_one({"id": inv_id}, {"$push": {"containers": c}})
    inv = db.inventories.find_one({"id": inv_id}, {"_id":0})
    return {"status":"success","container": c, "inventory": inv}

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

@app.post("/inventories/{inv_id}/purchase")
def purchase_item(request: Request, inv_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv: raise HTTPException(404, "Not found")

    kind = (payload.get("kind") or "").strip().lower()
    ref_id = (payload.get("ref_id") or "").strip()
    qty = max(1, int(payload.get("quantity") or 1))
    quality = (payload.get("quality") or "Adequate").strip()  # kept for future-proof; ignored for objects
    container_id = (payload.get("container_id") or (inv["containers"][0]["id"] if inv.get("containers") else None))
    upgrades_req = payload.get("upgrades") or []
    currency = (payload.get("currency") or "Jelly").strip()

    src = _fetch_catalog_item(kind, ref_id)
    if not src: raise HTTPException(404, "Catalog item not found")

    base_price = int(src.get("price") or 0)
    enc = float(src.get("enc") or 0.0)
    subcat = src.get("category") if kind == "equipment" else None
    name = src.get("name") or (subcat == "armor" and f"Armor — {src.get('type')}") or src.get("style") or "Item"

    unit_price = base_price
    if kind in ("weapon", "equipment"):
        # quality/upgrades supported if you need them later
        unit_price = _qprice(base_price, quality)
        upgrades, fee, steps = _validate_upgrades(kind, subcat, quality, existing=[], add=upgrades_req)
        unit_price += fee
    else:
        upgrades = []

    total = unit_price * qty

    # money (negative transaction)
    cur = inv.get("currencies", {})
    cur[currency] = int(cur.get(currency, 0)) - total

    # NEW: encumbrance roll-up into container (and maybe inventory)
    delta_enc = enc * qty
    containers = inv.get("containers", [])[:]
    includes = True
    if containers:
        found = False
        for c in containers:
            if c.get("id") == container_id:
                c["enc_total"] = float(c.get("enc_total", 0.0)) + float(delta_enc)
                c["include"] = bool(c.get("include", True))
                includes = c["include"]
                found = True
                break
        if not found:
            # fallback to first container
            containers[0]["enc_total"] = float(containers[0].get("enc_total", 0.0)) + float(delta_enc)
            containers[0]["include"] = bool(containers[0].get("include", True))
            includes = containers[0]["include"]
            container_id = containers[0]["id"]

    inv_enc_total = float(inv.get("enc_total", 0.0))
    if includes:
        inv_enc_total += float(delta_enc)

    # store item + transaction
    item = {
        "item_id": next_id_str("invitem", padding=5),
        "kind": kind,
        "subcategory": subcat,
        "ref_id": ref_id,
        "name": name,
        "quantity": qty,
        "quality": (quality if kind in ("weapon", "equipment") else None),
        "enc": enc,
        "base_price": base_price,
        "paid_unit": unit_price,
        "upgrades": upgrades,
        "container_id": container_id,
    }
    tx = {"ts": datetime.datetime.utcnow().isoformat() + "Z",
          "currency": currency, "amount": -total,
          "note": f"Purchase {name} x{qty}", "source": "purchase"}

    db.inventories.update_one({"id": inv_id}, {
        "$set": {"currencies": cur, "containers": containers, "enc_total": inv_enc_total},
        "$push": {"transactions": tx, "items": item}
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
    add_list = [{"key": k} for k in add_keys]
    new_upgrades, fee, steps = _validate_upgrades(kind, subcat, it.get("quality") or "Adequate", it.get("upgrades") or [], add_list)
    if len(new_upgrades) > len(it.get("upgrades") or []):
        it["upgrades"] = new_upgrades
        total_cost += fee
        note_parts.append(f"+{len(new_upgrades)-(len(it.get('upgrades') or []))} upgrade(s)")

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
def catalog_objects(request: Request, q: str = "", limit: int = 25):
    require_auth(request)
    col = get_col("objects")
    filt = {}
    if q.strip():
        filt = {"name": {"$regex": re.escape(q.strip()), "$options": "i"}}
    rows = list(col.find(filt, {"_id": 0, "id": 1, "name": 1, "price": 1, "enc": 1}).limit(int(limit)))
    return {"status": "success", "objects": rows}

@app.post("/inventories/{inv_id}/containers")
def add_container(request: Request, inv_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv: 
        raise HTTPException(404, "Inventory not found")
    name = (payload.get("name") or "Container").strip()
    cont = _new_container(name)
    containers = (inv.get("containers") or []) + [cont]
    # recompute inventory enc_total = sum enc_total of containers where include==True
    new_enc_total = sum(float(c.get("enc_total", 0.0)) for c in containers if bool(c.get("include", True)))
    db.inventories.update_one({"id": inv_id}, {"$set": {"containers": containers, "enc_total": new_enc_total}})
    inv2 = db.inventories.find_one({"id": inv_id}, {"_id": 0})
    return {"status": "success", "inventory": inv2}

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
    if amount <= 0:
        raise HTTPException(400, "Amount must be positive")

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

@app.patch("/inventories/{inv_id}/items/{item_id}")
def patch_item(request: Request, inv_id: str, item_id: str, payload: dict = Body(...)):
    user, role = require_auth(request)
    db = get_db()
    inv = db.inventories.find_one({"id": inv_id, "owner": user})
    if not inv:
        raise HTTPException(404, "Inventory not found")

    alt_name = payload.get("alt_name", None)
    if alt_name is None:
        raise HTTPException(400, "Nothing to update")

    # positional update on array item
    res = db.inventories.update_one(
        {"id": inv_id, "owner": user, "items.item_id": item_id},
        {"$set": {"items.$.alt_name": (alt_name or "").strip()}}
    )
    if res.matched_count == 0:
        raise HTTPException(404, "Item not found")

    inv2 = db.inventories.find_one({"id": inv_id}, {"_id": 0})
    return {"status": "success", "inventory": inv2}

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

    upg_key = (payload.get("upgrade") or "").strip()
    if not upg_key:
        raise HTTPException(400, "Missing upgrade key/name")

    kind = it.get("kind")
    subcat = it.get("subcategory")
    quality = it.get("quality") or "Adequate"
    existing = it.get("upgrades") or []

    # validate & price the upgrade (expects fee PER UNIT)
    try:
        upgrades, fee_per_unit, steps = _validate_upgrades(kind, subcat, quality, existing=existing, add=[upg_key])
    except Exception as e:
        raise HTTPException(400, f"Upgrade invalid: {e}")

    qty = int(it.get("quantity") or 1)
    delta_total = int(fee_per_unit) * qty
    currency = _pick_currency(inv, (payload.get("currency") or None))

    curmap = inv.get("currencies", {})
    curmap[currency] = int(curmap.get(currency, 0)) - delta_total

    new_paid_unit = int(it.get("paid_unit") or _qprice(int(it.get("base_price") or 0), quality)) + int(fee_per_unit)
    new_variant = _compose_variant(quality, upgrades)

    tx = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "currency": currency,
        "amount": -delta_total,
        "note": f'Install upgrade "{upg_key}" on {it.get("name","Item")}',
        "source": "install_upgrade",
        "item_id": item_id
    }

    db.inventories.update_one(
        {"id": inv_id, "owner": user, "items.item_id": item_id},
        {
            "$set": {
                "currencies": curmap,
                "items.$.upgrades": upgrades,
                "items.$.paid_unit": new_paid_unit,
                "items.$.variant": new_variant
            },
            "$push": {"transactions": tx}
        }
    )
    inv2 = db.inventories.find_one({"id": inv_id}, {"_id": 0})
    return {"status": "success", "inventory": inv2, "transaction": tx}

@app.get("/catalog/weapons")
def catalog_weapons(request: Request, q: str = "", limit: int = 50):
    require_auth(request)
    col = get_col("weapons")
    filt = {"name": {"$regex": re.escape(q.strip()), "$options": "i"}} if q.strip() else {}
    rows = list(col.find(filt, {"_id": 0, "id": 1, "name": 1, "price": 1, "enc": 1, "subcategory": 1}).limit(int(limit)))
    return {"status": "success", "weapons": rows}

@app.get("/catalog/equipment")
def catalog_equipment(request: Request, q: str = "", limit: int = 50):
    require_auth(request)
    col = get_col("equipment")
    filt = {"name": {"$regex": re.escape(q.strip()), "$options": "i"}} if q.strip() else {}
    rows = list(col.find(filt, {"_id": 0, "id": 1, "name": 1, "price": 1, "enc": 1, "category": 1}).limit(int(limit)))
    return {"status": "success", "equipment": rows}

@app.get("/catalog/tools")
def catalog_tools(request: Request, q: str = "", limit: int = 50):
    require_auth(request)
    col = get_col("tools")
    filt = {"name": {"$regex": re.escape(q.strip()), "$options": "i"}} if q.strip() else {}
    rows = list(col.find(filt, {"_id": 0, "id": 1, "name": 1, "price": 1, "enc": 1, "category": 1}).limit(int(limit)))
    return {"status": "success", "tools": rows}