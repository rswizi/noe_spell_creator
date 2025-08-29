"""
One-off migration script: JSON files -> MongoDB
------------------------------------------------
How to use:
1) Install deps:  pip install pymongo
2) Adjust the constants below (MONGO_URI, DB_NAME, DATA_ROOT) to match your setup.
3) Run:  python migrate_to_mongo.py

Collections created:
  - schools
  - effects
  - spells
  - audit_logs  (optional: reuses your existing audit file if present)
  - counters    (optional: sets the next id if you want to keep zero-padded incremental ids)

Notes:
  - We store IDs as strings (e.g., "0001").
  - For effects, we normalize school to be a string "school": "<id>".
  - For spells, we normalize effects to be an array of string ids.
  - This script is idempotent: it upserts by "id" for schools/effects/spells.
"""
import os
import json
from pathlib import Path
from typing import Dict, Any, List
from pymongo import MongoClient, UpdateOne

# ---------- EDIT THESE ----------
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME   = os.environ.get("DB_NAME", "noe_spell_creator")
# If you launched your FastAPI from project root, DATA_ROOT probably matches this pattern:
#   server/data/{effects,spells,schools,logs}
DATA_ROOT = os.environ.get("DATA_ROOT", os.path.join(os.getcwd(), "server", "data"))
# --------------------------------

EFFECTS_DIR = os.path.join(DATA_ROOT, "effects")
SPELLS_DIR  = os.path.join(DATA_ROOT, "spells")
SCHOOLS_DIR = os.path.join(DATA_ROOT, "schools")
LOGS_DIR    = os.path.join(DATA_ROOT, "logs")
AUDIT_LOG   = os.path.join(LOGS_DIR, "audit.log")

def read_json_files(folder: str) -> List[Dict[str, Any]]:
    rows = []
    if not os.path.isdir(folder):
        return rows
    for fn in os.listdir(folder):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(folder, fn)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            rows.append(data)
        except Exception as e:
            print(f"[WARN] Failed to read {path}: {e}")
    return rows

def main():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    schools_col = db["schools"]
    effects_col = db["effects"]
    spells_col  = db["spells"]
    logs_col    = db["audit_logs"]
    counters    = db["counters"]

    # --- migrate schools ---
    schools = read_json_files(SCHOOLS_DIR)
    ops = []
    max_sid = -1
    for s in schools:
        sid = str(s.get("id") or "").strip()
        if not sid:
            print("[WARN] School without id, skipping:", s)
            continue
        # retro-compat: rename is_upgrade -> upgrade
        if "upgrade" not in s and "is_upgrade" in s:
            s["upgrade"] = bool(s.pop("is_upgrade"))
        ops.append(UpdateOne({"id": sid}, {"$set": s}, upsert=True))
        try:
            max_sid = max(max_sid, int(sid))
        except Exception:
            pass
    if ops:
        res = schools_col.bulk_write(ops)
        print(f"[OK] Schools upserted: {res.upserted_count} (matched {res.matched_count})")
    if max_sid >= 0:
        counters.update_one({"_id":"schools"}, {"$set":{"next": max_sid+1}}, upsert=True)

    # --- migrate effects ---
    effects = read_json_files(EFFECTS_DIR)
    ops = []
    max_eid = -1
    for e in effects:
        eid = str(e.get("id") or "").strip()
        if not eid:
            print("[WARN] Effect without id, skipping:", e)
            continue

        # normalize "school" to string id
        sch = e.get("school")
        if isinstance(sch, dict) and "id" in sch:
            e["school"] = str(sch["id"])
        else:
            e["school"] = str(sch or "")

        ops.append(UpdateOne({"id": eid}, {"$set": e}, upsert=True))
        try:
            max_eid = max(max_eid, int(eid))
        except Exception:
            pass
    if ops:
        res = effects_col.bulk_write(ops)
        print(f"[OK] Effects upserted: {res.upserted_count} (matched {res.matched_count})")
    if max_eid >= 0:
        counters.update_one({"_id":"effects"}, {"$set":{"next": max_eid+1}}, upsert=True)

    # --- migrate spells ---
    spells = read_json_files(SPELLS_DIR)
    ops = []
    max_pid = -1
    for sp in spells:
        sid = str(sp.get("id") or "").strip()
        if not sid:
            print("[WARN] Spell without id, skipping:", sp)
            continue

        # ensure effects is list of string ids
        effs = sp.get("effects") or []
        eff_ids = []
        for x in effs:
            if isinstance(x, dict) and "id" in x:
                eff_ids.append(str(x["id"]))
            else:
                eff_ids.append(str(x))
        sp["effects"] = eff_ids

        ops.append(UpdateOne({"id": sid}, {"$set": sp}, upsert=True))
        try:
            max_pid = max(max_pid, int(sid))
        except Exception:
            pass
    if ops:
        res = spells_col.bulk_write(ops)
        print(f"[OK] Spells upserted: {res.upserted_count} (matched {res.matched_count})")
    if max_pid >= 0:
        counters.update_one({"_id":"spells"}, {"$set":{"next": max_pid+1}}, upsert=True)

    # --- optional: migrate audit log lines (JSONL) ---
    if os.path.isfile(AUDIT_LOG):
        try:
            with open(AUDIT_LOG, "r", encoding="utf-8") as f:
                bulk = []
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        doc = json.loads(line)
                        bulk.append(doc)
                    except Exception:
                        pass
                if bulk:
                    logs_col.insert_many(bulk)
                    print(f"[OK] Audit log lines inserted: {len(bulk)}")
        except Exception as e:
            print(f"[WARN] Failed to migrate audit log: {e}")

    print("\n[DONE] Migration complete.")
    print(f"MongoDB: {MONGO_URI}  DB: {DB_NAME}")
    print("Collections -> schools, effects, spells, audit_logs, counters")

if __name__ == "__main__":
    main()
