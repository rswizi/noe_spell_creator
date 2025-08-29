# wsgi_app.py — Flask wrapper around your current logic so it can run on WSGI

import os, json
from flask import Flask, request, jsonify
from typing import Optional

# ---- Project paths and env ----
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_ROOT)
os.environ.setdefault("DATA_ROOT", os.path.join(PROJECT_ROOT, "server", "data"))

# ---- Import your existing helpers/objects ----
from server.src.objects.effects import load_effect
from server.src.objects.spells import Spell, load_spell
from server.src.objects.schools import load_school

# (The following constants mirror your FastAPI main.py)
DATA_ROOT = os.getenv("DATA_ROOT", os.path.join(PROJECT_ROOT, "server", "data"))
EFFECTS_DIR = os.path.join(DATA_ROOT, "effects")
SPELLS_DIR  = os.path.join(DATA_ROOT, "spells")
SCHOOLS_DIR = os.path.join(DATA_ROOT, "schools")
LOGS_DIR    = os.path.join(DATA_ROOT, "logs")
USERS_FILE  = os.path.join(DATA_ROOT, "users.txt")

for d in (EFFECTS_DIR, SPELLS_DIR, SCHOOLS_DIR, LOGS_DIR):
    os.makedirs(d, exist_ok=True)

app = Flask(__name__)
application = app   # <- WSGI entrypoint

# ---- Simple in-memory session (same caveat as before) ----
SESSIONS = {}  # token -> (username, role)

def get_auth_token():
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None

# ----------------- ROUTES -----------------

@app.get("/")
def root():
    return jsonify({"Hello": "World"})

@app.get("/__debug/where")
def where():
    return jsonify({
        "DATA_ROOT": DATA_ROOT,
        "EFFECTS_DIR": EFFECTS_DIR,
        "SPELLS_DIR": SPELLS_DIR,
        "SCHOOLS_DIR": SCHOOLS_DIR,
        "USERS_FILE": USERS_FILE,
    })

@app.get("/effects")
def get_effects():
    name = request.args.get("name")
    school = request.args.get("school")

    effects = []
    for filename in os.listdir(EFFECTS_DIR):
        if not filename.endswith(".json"):
            continue
        file_path = os.path.join(EFFECTS_DIR, filename)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                eff = json.load(f)

            sch = eff.get("school")
            if isinstance(sch, dict) and "id" in sch:
                eff["school"] = sch["id"]

            school_id = eff.get("school")
            school_name = ""
            if isinstance(school_id, str) and school_id:
                try:
                    s = load_school(school_id)
                    school_name = getattr(s, "name", school_id)
                except Exception:
                    school_name = school_id
            eff["school_name"] = school_name

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
    return jsonify({"effects": effects})

@app.post("/costs")
def get_costs():
    try:
        body = request.get_json(force=True) or {}
        range_val = body.get("range")
        aoe_val = body.get("aoe")
        duration_val = body.get("duration")
        activation_val = body.get("activation")
        effect_ids = [eid for eid in body.get("effects", []) if eid and str(eid).strip()]

        effects = [load_effect(eid) for eid in effect_ids]
        temp = Spell(
            id="__preview__",
            name="__preview__",
            activation=activation_val,
            range=range_val,
            aoe=aoe_val,
            duration=duration_val,
            effects=effects
        )
        temp.update_cost()
        temp.set_spell_category()

        return jsonify({"mp_cost": temp.mp_cost, "en_cost": temp.en_cost, "category": temp.category})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.get("/schools")
def list_schools():
    out = []
    for fname in os.listdir(SCHOOLS_DIR):
        if not fname.endswith(".json"):
            continue
        sid = os.path.splitext(fname)[0]
        try:
            s = load_school(sid)
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
    return jsonify({"schools": out})

@app.get("/spells")
def list_spells():
    name = request.args.get("name")
    category = request.args.get("category")
    school = request.args.get("school")

    rows = []
    for fname in os.listdir(SPELLS_DIR):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(SPELLS_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        if name and name.lower() not in (data.get("name", "").lower()):
            continue
        if category and category != data.get("category"):
            continue

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
            "schools": school_list,
        })

    rows.sort(key=lambda r: (r["id"] is None, r["id"]))
    return jsonify({"spells": rows})

@app.get("/spells/<spell_id>")
def get_spell(spell_id):
    try:
        spell = load_spell(spell_id)
        spell.update_cost()
        spell.set_spell_category()
        return jsonify({"spell": spell.to_dict()})
    except FileNotFoundError:
        return jsonify({"error": f"Spell {spell_id} not found"})
    except Exception as e:
        return jsonify({"error": str(e)})

# ---- Auth subset (simple; mirrors your current behavior) ----
import secrets
def make_token(): return secrets.token_hex(16)
def load_users():
    users = {}
    if not os.path.exists(USERS_FILE): return users
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"): continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 3: continue
            users[parts[0]] = {"password": parts[1], "role": parts[2]}
    return users

@app.post("/auth/login")
def auth_login():
    body = request.get_json(force=True) or {}
    username = (body.get("username") or "").strip()
    password = (body.get("password") or "").strip()
    users = load_users()
    info = users.get(username)
    if not info or info["password"] != password:
        return jsonify({"status": "error", "message": "Invalid username or password"})
    token = make_token()
    SESSIONS[token] = (username, info["role"])
    return jsonify({"status": "success", "token": token, "username": username, "role": info["role"]})

@app.get("/auth/me")
def auth_me():
    token = get_auth_token()
    if not token or token not in SESSIONS:
        return jsonify({"status": "error", "message": "Not authenticated"})
    username, role = SESSIONS[token]
    return jsonify({"status": "success", "username": username, "role": role})

@app.post("/auth/logout")
def auth_logout():
    token = get_auth_token()
    if token and token in SESSIONS:
        del SESSIONS[token]
    return jsonify({"status": "success"})
