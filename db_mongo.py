from functools import lru_cache
from typing import List
import os
import re
import json
import hashlib

from pymongo import MongoClient, ReturnDocument, ASCENDING
from pymongo.errors import ConfigurationError
from pymongo.database import Database
from settings import settings

try:
    import mongomock
except ImportError:  # pragma: no cover
    mongomock = None


def _normalize_mongodb_uri(uri: str) -> str:
    return (uri or "").strip()


def _create_client() -> MongoClient:
    uri = _normalize_mongodb_uri(settings.mongodb_uri)
    if not uri or "xxxx.mongodb.net" in uri or "example.com" in uri:
        raise RuntimeError("MONGODB_URI is missing or still a placeholder.")
    if uri.startswith("mongomock://"):
        if not mongomock:
            raise RuntimeError("mongomock is required for mongomock:// URIs")
        return mongomock.MongoClient()
    return MongoClient(uri)


@lru_cache
def get_client() -> MongoClient:
    return _create_client()


def get_db() -> Database:
    client = get_client()
    try:
        db = client.get_default_database()
    except ConfigurationError:
        db = None
    if db:
        return db
    db_name = os.getenv("DB_NAME") or "NoeSpellCreator"
    return client[db_name]


def get_col(name: str):
    return get_db()[name]


def norm_key(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).lower()


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
    db.tools.create_index("id", unique=True)
    db.tools.create_index("name_key", unique=True)
    db.equipment.create_index("id", unique=True)
    db.equipment.create_index([("category", 1), ("name_key", 1)], unique=True)
    db.inventories.create_index("id", unique=True)
    db.inventories.create_index("owner")
    db.characters.create_index("id", unique=True)
    db.characters.create_index("owner")
    db.characters.create_index("name_key")
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
    db.campaign_chat.create_index("id", unique=True)
    db.campaign_chat.create_index([("campaign_id", ASCENDING), ("ts", ASCENDING)])
    db.campaign_combats.create_index("id", unique=True)
    db.campaign_combats.create_index("campaign_id")


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
    max_chat = 0
    for d in db.campaign_chat.find({}, {"id": 1, "_id": 0}):
        raw = str(d.get("id") or "")
        match = re.search(r"(\d+)$", raw)
        if not match:
            continue
        try:
            max_chat = max(max_chat, int(match.group(1)))
        except Exception:
            pass
    if max_chat:
        db.counters.update_one({"_id": "campaign_chat"}, {"$max": {"seq": max_chat}}, upsert=True)


def spell_sig(activation: str, range_val: int, aoe: str, duration: int, effect_ids: List[str]) -> str:
    payload = {
        "activation": (activation or "").strip().lower(),
        "range": int(range_val or 0),
        "aoe": (aoe or "").strip().lower(),
        "duration": int(duration or 0),
        "effects": sorted([str(e).strip() for e in (effect_ids or []) if str(e).strip()]),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
