import os
from typing import Any
from pymongo import MongoClient, ReturnDocument
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME   = os.getenv("DB_NAME",   "noe_spell_creator")

_client = MongoClient(MONGO_URI)

def get_db():
    return _client[DB_NAME]

def get_col(name: str):
    return get_db()[name]

def ensure_indexes():
    db = get_db()
    # id fields unique; users.username unique
    db.spells.create_index("id", unique=True)
    db.effects.create_index("id", unique=True)
    db.schools.create_index("id", unique=True)
    db.users.create_index("username", unique=True)

def next_id_str(sequence_name: str, padding: int = 4) -> str:
    """
    Monotonic ID per collection using a 'counters' collection.
    Doc form: { _id: <sequence_name>, seq: <int> }
    """
    doc = get_db().counters.find_one_and_update(
        {"_id": sequence_name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return str(doc["seq"]).zfill(padding)
