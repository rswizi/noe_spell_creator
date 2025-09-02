# db_mongo.py
import os, re, certifi
from dotenv import load_dotenv
from pymongo import MongoClient, ReturnDocument, ASCENDING
import json, hashlib, re
from pymongo import MongoClient
from settings import settings

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://rswizi:Wyp9h8zvnxq69%2Amangodb@noespellcreator.kftlncu.mongodb.net/?retryWrites=true&w=majority&appName=NoeSpellCreator")
DB_NAME   = os.getenv("DB_NAME", "NoeSpellCreator")

client = MongoClient(settings.mongodb_uri)
_db = client["noe"]

def get_db(): return _db
def get_col(name: str): return _db[name]

def ensure_indexes():
    db = get_db()
    db.spells.create_index("id", unique=True)
    db.effects.create_index("id", unique=True)
    db.schools.create_index("id", unique=True)
    db.users.create_index("username", unique=True)

    # optional helpers; non-unique is fine
    db.spells.create_index("name_key")
    db.effects.create_index("name_key")
    db.schools.create_index("name_key")

    # NEW: de-duplication by full parameter signature (unique)
    db.spells.create_index(
        "sig_v1",
        unique=True,
        partialFilterExpression={"sig_v1": {"$exists": True}}
    )

    # keep the effect uniqueness (name+school) if you already added it
    db.effects.create_index(
        [("name_key", ASCENDING), ("school", ASCENDING)],
        unique=True,
        partialFilterExpression={
            "name_key": {"$exists": True, "$type": "string"},
            "school": {"$exists": True, "$type": "string"},
        },
    )

def next_id_str(sequence_name: str, padding: int = 4) -> str:
    doc = get_db().counters.find_one_and_update(
        {"_id": sequence_name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return str(doc["seq"]).zfill(padding)

def _max_numeric_id(colname: str) -> int:
    doc = get_col(colname).find({}, {"id": 1}).sort("id", -1).limit(1)
    doc = next(doc, None)
    if not doc:
        return 0
    s = str(doc.get("id", "")).lstrip("0") or "0"
    try:
        return int(s)
    except:
        return 0

def sync_counters():
    db = get_db()
    for coll, field in [("effects", "id"), ("schools", "id"), ("spells", "id")]:
        max_id = 0
        for d in db[coll].find({}, {field: 1, "_id": 0}):
            try:
                max_id = max(max_id, int(str(d.get(field, "0")).lstrip("0") or "0"))
            except Exception:
                pass
        db.counters.update_one({"_id": coll}, {"$max": {"seq": max_id}}, upsert=True)

def norm_key(s: str) -> str:
    """Lowercase + collapse whitespace for uniqueness keys."""
    return re.sub(r"\s+", " ", (s or "").strip()).lower()

def spell_sig(activation: str, range_val: int, aoe: str, duration: int, effect_ids: list[str]) -> str:
    """Canonical hash of the parameters that define spell identity (NOT the name)."""
    payload = {
        "activation": (activation or "").strip().lower(),
        "range": int(range_val or 0),
        "aoe": (aoe or "").strip().lower(),
        "duration": int(duration or 0),
        "effects": sorted([str(e).strip() for e in (effect_ids or []) if str(e).strip()]),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()