from functools import lru_cache
from urllib.parse import urlparse
from typing import List
from pymongo import MongoClient, ReturnDocument, ASCENDING
from pymongo.database import Database
from settings import settings
import json, hashlib, re
import os

_client = MongoClient(settings.mongodb_uri)

def norm_key(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()

@lru_cache
def get_client() -> MongoClient:
    uri = settings.mongodb_uri
    if not uri or "xxxx.mongodb.net" in uri or "example.com" in uri:
        raise RuntimeError("MONGODB_URI is missing or still a placeholder.")
    return MongoClient(uri)

def get_db() -> Database:
    client = get_client()
    db = client.get_default_database()
    return db if db is not None else client["noe"]

def get_col(name: str):
    return get_db()[name]

def ensure_indexes() -> None:
    db = get_db()
    db.spells.create_index("id", unique=True)
    db.objects.create_index("id", unique=True)
    db.objects.create_index("name_key")
    db.effects.create_index("id", unique=True)
    db.schools.create_index("id", unique=True)
    db.users.create_index("username", unique=True)
    db.spells.create_index("name_key")
    db.effects.create_index("name_key")
    db.schools.create_index("name_key")
    db.spells.create_index(
        "sig_v1",
        unique=True,
        partialFilterExpression={"sig_v1": {"$exists": True}},
    )
    db.effects.create_index(
        [("name_key", ASCENDING), ("school", ASCENDING)],
        unique=True,
        partialFilterExpression={
            "name_key": {"$exists": True, "$type": "string"},
            "school": {"$exists": True, "$type": "string"},
        },
    )

def next_id_str(sequence_name: str, padding: int = 4) -> str:
    doc = get_col("counters").find_one_and_update(
        {"_id": sequence_name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return str(doc["seq"]).zfill(padding)

def sync_counters() -> None:
    db = get_db()
    for coll in ("effects", "schools", "spells"):
        max_id = 0
        for d in db[coll].find({}, {"id": 1, "_id": 0}):
            try:
                max_id = max(max_id, int(str(d.get("id", "0")).lstrip("0") or "0"))
            except Exception:
                pass
        db.counters.update_one({"_id": coll}, {"$max": {"seq": max_id}}, upsert=True)

def spell_sig(activation: str, range_val: int, aoe: str, duration: int, effect_ids: List[str]) -> str:
    """Stable signature for a spell's parameters (NOT the name)."""
    payload = {
        "activation": (activation or "").strip().lower(),
        "range": int(range_val or 0),
        "aoe": (aoe or "").strip().lower(),
        "duration": int(duration or 0),
        "effects": sorted([str(e).strip() for e in (effect_ids or []) if str(e).strip()]),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def _db_name_from_uri_fallback() -> str:
    u = urlparse(settings.mongodb_uri or "")
    return (u.path or "").lstrip("/") or os.getenv("DB_NAME") or "noe_spell_creator"

def get_db() -> Database:
    return _client[_db_name_from_uri_fallback()]