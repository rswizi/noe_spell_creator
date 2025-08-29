from dotenv import load_dotenv
load_dotenv()

import os
from pymongo import MongoClient, ReturnDocument

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME   = os.environ.get("DB_NAME", "noe_spell_creator")

_client = None
_db = None

def get_db():
    global _client, _db
    if _db is None:
        _client = MongoClient(MONGO_URI)
        _db = _client[DB_NAME]
    return _db

def get_col(name: str):
    return get_db()[name]

def next_id_str(counter_name: str, padding: int = 4) -> str:
    """
    Atomically increments the counter and returns zero-padded string id.
    Example: next_id_str("effects") -> "0004"
    """
    col = get_col("counters")
    doc = col.find_one_and_update(
        {"_id": counter_name},
        {"$inc": {"next": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    n = int(doc.get("next", 0))
    # If this is the first call and "next" was created as 1, you may want previous value.
    # Use n-1 if you prefer. Here we assume the new value is the new id.
    return f"{n:0{padding}d}"

def ensure_indexes():
    db = get_db()
    db.schools.create_index("id", unique=True)
    db.effects.create_index("id", unique=True)
    db.spells.create_index("id", unique=True)
    db.effects.create_index("name")
    db.spells.create_index("name")
    db.schools.create_index("name")
