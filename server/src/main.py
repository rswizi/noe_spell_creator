import os
import json
import uvicorn
import sys
import secrets
import datetime
import json
import os
from typing import Optional, Tuple
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Query
from typing import Dict, Tuple
from fastapi import HTTPException


from src.objects.effects import load_effect
from src.objects.spells import Spell, load_spell
from src.objects.schools import load_school


# Create app instance
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Absolute path to /data/effects regardless of run location
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EFFECTS_DIR = os.path.join(BASE_DIR, "..", "data", "effects")
SPELLS_DIR = os.path.join(BASE_DIR, "..", "data", "spells")
os.makedirs(SPELLS_DIR, exist_ok=True)
SCHOOLS_DIR = os.path.join(BASE_DIR, "..", "data", "schools")
os.makedirs(SCHOOLS_DIR, exist_ok=True)
USERS_FILE = os.path.join(BASE_DIR, "..", "data", "users.txt")
SESSIONS: Dict[str, Tuple[str, str]] = {}  # token -> (username, role)
LOGS_DIR = os.path.join(BASE_DIR, "..", "data", "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
AUDIT_LOG = os.path.join(LOGS_DIR, "db_audit.log")

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
    """Find the highest numeric ID in /data/spells and return next one as zero-padded string."""
    existing_ids = []
    for fname in os.listdir(SPELLS_DIR):
        if fname.endswith(".json"):
            try:
                existing_ids.append(int(os.path.splitext(fname)[0]))
            except ValueError:
                continue
    next_id = (max(existing_ids) + 1) if existing_ids else 0
    return f"{next_id:04d}"

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
    existing_ids = []
    for fname in os.listdir(EFFECTS_DIR):
        if fname.endswith(".json"):
            try:
                existing_ids.append(int(os.path.splitext(fname)[0]))
            except ValueError:
                pass
    next_id = (max(existing_ids) + 1) if existing_ids else 0
    return f"{next_id:04d}"

def get_next_school_id() -> str:
    existing_ids = []
    for fname in os.listdir(SCHOOLS_DIR):
        if fname.endswith(".json"):
            try:
                existing_ids.append(int(os.path.splitext(fname)[0]))
            except ValueError:
                pass
    next_id = (max(existing_ids) + 1) if existing_ids else 0
    return f"{next_id:04d}"

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
        # admin only
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
        if not effects or not isinstance(effects, list):
            raise HTTPException(status_code=400, detail="effects must be a non-empty list")

        # make/find school
        school = ensure_school(school_name, school_type, range_type, aoe_type, upgrade)

        created = []
        for e in effects:
            name = (e.get("name") or "").strip()
            desc = (e.get("description") or "").strip()
            mp   = e.get("mp_cost")
            en   = e.get("en_cost")

            if not name:
                raise HTTPException(status_code=400, detail="Effect name missing")
            # numeric guard
            try:
                mp = int(mp)
                en = int(en)
            except Exception:
                raise HTTPException(status_code=400, detail=f"Non-numeric MP/EN in effect '{name}'")

            eff_id = get_next_effect_id()
            rec = {
                "id": eff_id,
                "name": name,
                "description": desc,
                "mp_cost": mp,
                "en_cost": en,
                "school": school["id"]
            }
            with open(os.path.join(EFFECTS_DIR, f"{eff_id}.json"), "w", encoding="utf-8") as f:
                json.dump(rec, f, ensure_ascii=False, indent=2)
            created.append(rec["id"])

        # audit
        write_audit(
            "bulk_create_effects",
            username,
            spell_id="—", 
            before=None,
            after={
                "school": school,
                "range_type": range_type,
                "aoe_type": aoe_type,
                "upgrade": upgrade,
                "created": created
            }
        )

        return {
            "status": "success",
            "school": {
                "id": school["id"],
                "name": school["name"],
                "school_type": school["school_type"],
                "upgrade": school.get("upgrade", False),
                "range_type": school.get("range_type"),
                "aoe_type": school.get("aoe_type")
            },
            "created": created
        }

    except HTTPException as he:
        return {"status": "error", "message": he.detail}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.get("/effects")
def get_effects(name: str | None = Query(default=None), school: str | None = Query(default=None)):
    effects = []
    for filename in os.listdir(EFFECTS_DIR):
        if not filename.endswith(".json"):
            continue
        file_path = os.path.join(EFFECTS_DIR, filename)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                eff = json.load(f)

            # --- normalize school shape to string id for response ---
            # old: {"school":{"id":"0002"}}  -> new: {"school":"0002"}
            sch = eff.get("school")
            if isinstance(sch, dict) and "id" in sch:
                eff["school"] = sch["id"]

            # --- attach school_name (convenience for UI) ---
            school_id = eff.get("school")
            school_name = ""
            if isinstance(school_id, str) and school_id:
                try:
                    s = load_school(school_id)
                    school_name = getattr(s, "name", school_id)
                except Exception:
                    school_name = school_id
            eff["school_name"] = school_name

            # --- filters ---
            ok = True
            if name:
                ok = name.lower() in (eff.get("name", "").lower())
            if ok and school:
                sch_low = school.lower()
                sid = (eff.get("school") or "").lower()
                sname = (eff.get("school_name") or "").lower()
                ok = (sch_low in sid) or (sch_low in sname)

            if ok:
                effects.append(eff)

        except Exception as e:
            print(f"Error reading {file_path}: {e}")
    return {"effects": effects}

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
def list_schools():
    try:
        out = []
        for fname in os.listdir(SCHOOLS_DIR):
            if not fname.endswith(".json"):
                continue
            sid = os.path.splitext(fname)[0]
            try:
                s = load_school(sid)
                # rétro-compat
                upg = getattr(s, "upgrade", None)
                if upg is None:
                    upg = getattr(s, "is_upgrade", False)
                out.append({
                    "id": s.id,
                    "name": getattr(s, "name", s.id),
                    "school_type": getattr(s, "school_type", "simple"),
                    "upgrade": bool(upg),
                    "range_type": getattr(s, "range_type", None),
                    "aoe_type": getattr(s, "aoe_type", None),
                })
            except Exception:
                out.append({"id": sid, "name": sid, "school_type": "unknown", "upgrade": False})
        out.sort(key=lambda x: x["name"].lower())
        return {"schools": out}
    except Exception as e:
        return {"error": str(e)}

@app.get("/spells")
def list_spells(
    name: str | None = Query(default=None),
    category: str | None = Query(default=None),
    school: str | None = Query(default=None),   # school id or name
):
    rows = []
    for fname in os.listdir(SPELLS_DIR):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(SPELLS_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)  # effects are ids
        except Exception:
            continue

        # Basic filters
        if name and name.lower() not in (data.get("name", "").lower()):
            continue
        if category and category != data.get("category"):
            continue

        # Collect schools from effects
        effect_ids = data.get("effects", [])
        school_ids = set()
        school_list = []
        try:
            effect_objs = [load_effect(eid) for eid in effect_ids]
            for eff in effect_objs:
                sid = None
                sch_attr = getattr(eff, "school", None)
                if isinstance(sch_attr, str):
                    sid = sch_attr
                elif hasattr(sch_attr, "id"):
                    sid = getattr(sch_attr, "id", None)

                if not sid or sid in school_ids:
                    continue

                school_ids.add(sid)
                try:
                    s = load_school(sid)
                    school_list.append({"id": sid, "name": getattr(s, "name", sid)})
                except Exception:
                    school_list.append({"id": sid, "name": sid})

        except Exception:
            pass

        # School filter (accept id or name)
        if school:
            sch_lower = school.lower()
            ids_lower = {sid.lower() for sid in school_ids}
            names_lower = {sl["name"].lower() for sl in school_list}
            if sch_lower not in ids_lower and sch_lower not in names_lower:
                continue

        rows.append({
            "id": data.get("id"),
            "name": data.get("name"),
            "category": data.get("category"),
            "mp_cost": data.get("mp_cost", 0),
            "en_cost": data.get("en_cost", 0),
            "activation": data.get("activation"),
            "range": data.get("range"),
            "aoe": data.get("aoe"),
            "duration": data.get("duration"),
            "effects": data.get("effects", []),
            "spell_type": data.get("spell_type", "Simple"),
            "schools": school_list,  # <-- include id + name for display
        })

    rows.sort(key=lambda r: (r["id"] is None, r["id"]))
    return {"spells": rows}

@app.get("/spells/{spell_id}")
def get_spell(spell_id: str):
    try:
        # using loader ensures computed props are consistent
        spell = load_spell(spell_id)
        # ensure costs/category are current
        spell.update_cost()
        spell.set_spell_category()
        return {"spell": serialize_spell(spell)}
    except FileNotFoundError:
        return {"error": f"Spell {spell_id} not found"}
    except Exception as e:
        return {"error": str(e)}

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

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)