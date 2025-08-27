import os
import json
import uvicorn
import sys
import secrets
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Query
from typing import Dict, Tuple

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

def require_auth(request: Request, required_roles: list[str] | None = None):
    token = get_auth_token(request)
    if not token or token not in SESSIONS:
        raise Exception("Not authenticated")
    username, role = SESSIONS[token]
    if required_roles and role not in required_roles:
        raise Exception("Forbidden")
    return username, role

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.get("/effects")
def get_effects():
    effects = []
    for filename in os.listdir(EFFECTS_DIR):
        if filename.endswith(".json"):
            file_path = os.path.join(EFFECTS_DIR, filename)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    effect = json.load(f)
                    effects.append(effect)
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

        return {"status": "success", "id": spell.id, "saved": True}
    except Exception as e:
        return {"status": "error", "message": str(e)}


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
                out.append({
                    "id": s.id,
                    "name": getattr(s, "name", s.id),
                    "school_type": getattr(s, "school_type", "simple"),
                })
            except Exception:
                out.append({"id": sid, "name": sid, "school_type": "unknown"})
        # sort by name
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
                sid = getattr(getattr(eff, "school", None), "id", None)
                if not sid:
                    continue
                if sid in school_ids:
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


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)