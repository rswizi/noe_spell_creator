# db_mongo.py
import os, re, certifi
from dotenv import load_dotenv
from pymongo import MongoClient, ReturnDocument, ASCENDING
import json, hashlib, re
from pymongo import MongoClient
from settings import settings
from settings import settings
from functools import lru_cache
from urllib.parse import urlparse
from pymongo.database import Database

load_dotenv()

MONGODB_URI = settings.mongodb_uri
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

def _mask(uri: str) -> str:
    # don’t ever log secrets; just mask user:pass
    try:
        u = urlparse(uri)
        auth = "*****" if u.password or u.username else ""
        netloc = u.hostname or ""
        return f"{u.scheme}://{auth}@{netloc}{u.path or ''}"
    except Exception:
        return "<invalid-uri>"

@lru_cache
def get_client() -> MongoClient:
    uri = settings.mongodb_uri
    if not uri or "xxxx.mongodb.net" in uri or "example.com" in uri:
        raise RuntimeError("MONGODB_URI is missing or still a placeholder.")
    return MongoClient(uri)

def get_db(name="noe"):
    return get_client()[name]


def spell_sig(doc: dict) -> str:
    # your helper
    return f"{doc.get('name','').lower()}::{','.join(sorted(s['name'] for s in doc.get('schools',[])))}"

def ensure_indexes(db: Database):
    db["spells"].create_index("id", unique=True)
    db["spells"].create_index([("name", 1)])