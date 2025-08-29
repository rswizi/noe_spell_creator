import os
import json
import uvicorn
import sys
import secrets
import datetime
import json
import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Query
from typing import Dict, Tuple, Optional
from db_mongo import get_col, next_id_str
from db_mongo import get_db
from db_mongo import ensure_indexes


from server.src.objects.effects import load_effect
from server.src.objects.spells import Spell, load_spell
from server.src.objects.schools import load_school

ensure_indexes()

# Create app instance
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.getenv("DATA_ROOT", os.path.join(BASE_DIR, "server", "data"))

EFFECTS_DIR = os.path.join(DATA_ROOT, "effects")
SPELLS_DIR  = os.path.join(DATA_ROOT, "spells")
SCHOOLS_DIR = os.path.join(DATA_ROOT, "schools")
LOGS_DIR    = os.path.join(DATA_ROOT, "logs")
USERS_FILE  = os.path.join(DATA_ROOT, "users.txt")
AUDIT_LOG   = os.path.join(LOGS_DIR, "audit.log")

for d in (EFFECTS_DIR, SPELLS_DIR, SCHOOLS_DIR, LOGS_DIR):
    os.makedirs(d, exist_ok=True)

SESSIONS: Dict[str, Tuple[str, str]] = {}  # token -> (username, role)

def load_users():
    users = {}
    if not os.path.exists(USERS_FILE):
        return users
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 3:
                continue
            username, password, role = parts[0], parts[1], parts[2]
            users[username] = {"password": password, "role": role}
    return users

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

def write_audit(action: str, username: str, spell_id: str, before: dict | None, after: dict | None):
    entry = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "user": username,
        "action": action,          # "create", "update", "delete"
        "spell_id": spell_id,
        "before": before,
        "after": after,
    }
    with open(AUDIT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

# --- ID helpers ---
def get_next_effect_id() -> str:
    return next_id_str("effects", padding=4)

def get_next_school_id() -> str:
    return next_id_str("schools", padding=4)

def find_school_by_name(name: str) -> Optional[dict]:
    # naive scan
    for fname in os.listdir(SCHOOLS_DIR):
        if not fname.endswith(".json"):
            continue
        sid = os.path.splitext(fname)[0]
        try:
            with open(os.path.join(SCHOOLS_DIR, fname), "r", encoding="utf-8") as f:
                data = json.load(f)
            if (data.get("name") or "").strip().lower() == name.strip().lower():
                return data
        except Exception:
            pass
    return None

def save_school_record(sid: str, name: str, school_type: str,
                       range_type: str, aoe_type: str, upgrade: bool) -> dict:
    rec = {
        "id": sid,
        "name": name,
        "school_type": school_type,   # "Simple" | "Complex"
        "upgrade": bool(upgrade),     # <-- nouveau nom de champ
        "range_type": range_type,     # "A" | "B" | "C"
        "aoe_type": aoe_type          # "A" | "B" | "C"
    }
    with open(os.path.join(SCHOOLS_DIR, f"{sid}.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    return rec

def ensure_school(name: str, school_type: str,
                  range_type: str, aoe_type: str, upgrade: bool) -> dict:
    existing = find_school_by_name(name)
    if existing:
        # rétro-compat : 'is_upgrade' -> 'upgrade'
        if "upgrade" not in existing and "is_upgrade" in existing:
            existing["upgrade"] = bool(existing.get("is_upgrade"))
            existing.pop("is_upgrade", None)

        changed = False
        if existing.get("school_type") != school_type:
            existing["school_type"] = school_type; changed = True
        if existing.get("range_type") != range_type:
            existing["range_type"] = range_type; changed = True
        if existing.get("aoe_type") != aoe_type:
            existing["aoe_type"] = aoe_type; changed = True
        if bool(existing.get("upgrade")) != bool(upgrade):
            existing["upgrade"] = bool(upgrade); changed = True

        if changed:
            with open(os.path.join(SCHOOLS_DIR, f'{existing["id"]}.json'), "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
        return existing

    sid = get_next_school_id()
    return save_school_record(sid, name, school_type, range_type, aoe_type, upgrade)

# --- BULK CREATE EFFECTS (admin only) ---
from fastapi import HTTPException

@app.post("/effects/bulk_create")
async def bulk_create_effects(request: Request):
    try:
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

@app.get("/")
def read_root():
    return {"Hello": "World"}

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
    try:
        body = await request.json()
        range_val = body.get("range")
        aoe_val = body.get("aoe")
        duration_val = body.get("duration")
        activation_val = body.get("activation")
        effect_ids = [eid for eid in body.get("effects", []) if eid and str(eid).strip()]

        effects = [load_effect(eid) for eid in effect_ids]

        # Build a temp spell so it uses set_* methods and your cost_utils correctly
        temp = Spell(
            id="__preview__",
            name="__preview__",
            activation=activation_val,
            range=range_val,
            aoe=aoe_val,
            duration=duration_val,
            effects=effects
        )
        # Make sure update + category run (post_init usually does, but be explicit)
        temp.update_cost()
        temp.set_spell_category()

        return {
            "mp_cost": temp.mp_cost,
            "en_cost": temp.en_cost,
            "category": temp.category
        }
    except Exception as e:
        # Keep 200 for now, but return an error key so the UI can show it
        return {"error": str(e)}


@app.get("/schools")
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

@app.get("/spells")
def list_spells(
    name: str | None = Query(default=None),
    category: str | None = Query(default=None),
    school: str | None = Query(default=None),
):
    sp_col = get_col("spells")
    eff_col = get_col("effects")
    sch_col = get_col("schools")

    q = {}
    if name:
        q["name"] = {"$regex": name, "$options": "i"}
    if category:
        q["category"] = category

    spells = list(sp_col.find(q, {"_id": 0}))
    # Build school information per spell from its effect ids
    school_map = {s["id"]: s.get("name", s["id"]) for s in sch_col.find({}, {"_id": 0, "id": 1, "name": 1})}

    rows = []
    for sp in spells:
        eff_ids = [str(e) for e in (sp.get("effects") or [])]
        # fetch distinct schools for those effects
        sch_ids = set()
        if eff_ids:
            for e in eff_col.find({"id": {"$in": eff_ids}}, {"_id": 0, "school": 1}):
                sid = str(e.get("school") or "")
                if sid:
                    sch_ids.add(sid)

        school_list = [{"id": sid, "name": school_map.get(sid, sid)} for sid in sorted(sch_ids)]
        # school filter (accept id or name)
        if school:
            low = school.lower()
            if (low not in {s["id"].lower() for s in school_list}) and (low not in {s["name"].lower() for s in school_list}):
                continue

        rows.append({
            "id": sp.get("id"),
            "name": sp.get("name"),
            "activation": sp.get("activation"),
            "range": sp.get("range"),
            "aoe": sp.get("aoe"),
            "duration": sp.get("duration"),
            "mp_cost": sp.get("mp_cost"),
            "en_cost": sp.get("en_cost"),
            "category": sp.get("category"),
            "schools": school_list,
            "effects": sp.get("effects", []),
        })
    return {"spells": rows}

@app.get("/spells/{spell_id}")
def get_spell(spell_id: str):
    sp = get_col("spells").find_one({"id": spell_id}, {"_id": 0})
    if not sp:
        return {"error": f"Spell {spell_id} not found"}
    return {"spell": sp}

@app.post("/auth/login")
async def auth_login(request: Request):
    try:
        body = await request.json()
        username = (body.get("username") or "").strip()
        password = (body.get("password") or "").strip()

        users = load_users()
        info = users.get(username)
        if not info or info["password"] != password:
            return {"status": "error", "message": "Invalid username or password"}

        token = make_token()
        SESSIONS[token] = (username, info["role"])
        return {"status": "success", "token": token, "username": username, "role": info["role"]}
    except Exception as e:
        return {"status": "error", "message": str(e)}

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
        username, role = require_auth(request, ["admin", "moderator"])
        path = os.path.join(SPELLS_DIR, f"{spell_id}.json")
        if not os.path.exists(path):
            return {"status": "error", "message": f"Spell {spell_id} not found"}

        with open(path, "r", encoding="utf-8") as f:
            before = json.load(f)

        os.remove(path)
        write_audit("delete", username, spell_id, before, None)
        return {"status": "success", "deleted": spell_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.put("/spells/{spell_id}")
async def update_spell(spell_id: str, request: Request):
    try:
        username, role = require_auth(request, ["admin", "moderator"])
        path = os.path.join(SPELLS_DIR, f"{spell_id}.json")
        if not os.path.exists(path):
            return {"status": "error", "message": f"Spell {spell_id} not found"}

        body = await request.json()
        # expected keys: name, activation, range, aoe, duration, effects (ids)
        effect_ids = [eid for eid in body.get("effects", []) if eid and str(eid).strip()]
        effects = [load_effect(eid) for eid in effect_ids]

        with open(path, "r", encoding="utf-8") as f:
            before = json.load(f)

        # Rebuild spell using SAME id
        spell = Spell(
            id=spell_id,
            name=body.get("name") or before.get("name"),
            activation=body.get("activation") or before.get("activation"),
            range=body.get("range") if body.get("range") is not None else before.get("range"),
            aoe=body.get("aoe") or before.get("aoe"),
            duration=body.get("duration") if body.get("duration") is not None else before.get("duration"),
            effects=effects if effect_ids else [load_effect(eid) for eid in before.get("effects", [])],
        )
        spell.update_cost()
        spell.set_spell_category()
        spell.save(dir="spells")

        after = spell.to_dict()
        write_audit("update", username, spell_id, before, after)
        return {"status": "success", "id": spell_id, "saved": True}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/submit_spell")
async def submit_spell(request: Request):
    try:
        body = await request.json()
        name = body.get("name") or "Unnamed Spell"
        activation = body.get("activation")
        range_val = body.get("range")
        aoe_val = body.get("aoe")
        duration_val = body.get("duration")
        effect_ids = [eid for eid in body.get("effects", []) if eid and str(eid).strip()]

        effects = [load_effect(eid) for eid in effect_ids]

        # Auto-generate numeric ID
        spell_id = get_next_spell_id()

        spell = Spell(
            id=spell_id,
            name=name,
            activation=activation,
            range=range_val,
            aoe=aoe_val,
            duration=duration_val,
            effects=effects,
        )
        spell.update_cost()
        spell.set_spell_category()
        spell.save()

        # --- NEW: audit log for creation (works for any user) ---
        token = get_auth_token(request)               # reads 'Authorization: Bearer <token>'
        username = SESSIONS.get(token, ("anonymous", ""))[0] if token else "anonymous"
        write_audit("create", username, spell.id, before=None, after=spell.to_dict())

        return {"status": "success", "id": spell.id, "saved": True}
    except Exception as e:
        return {"status": "error", "message": str(e)}

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
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)