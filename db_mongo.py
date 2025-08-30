# db_mongo.py
import os, re, certifi
from dotenv import load_dotenv
from pymongo import MongoClient, ReturnDocument

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://rswizi:Wyp9h8zvnxq69%2Amangodb@noespellcreator.kftlncu.mongodb.net/?retryWrites=true&w=majority&appName=NoeSpellCreator")
DB_NAME   = os.getenv("DB_NAME", "NoeSpellCreator")

_client = MongoClient(MONGO_URI, tls=True, tlsCAFile=certifi.where())
_db = _client[DB_NAME]

def get_db(): return _db
def get_col(name: str): return _db[name]

def ensure_indexes():
    db = get_db()
    db.spells.create_index("id",     unique=True)
    db.effects.create_index("id",    unique=True)
    db.schools.create_index("id",    unique=True)
    db.users.create_index("username", unique=True)

def next_id_str(sequence_name: str, padding: int = 4) -> str:
    doc = get_db().counters.find_one_and_update(
        {"_id": sequence_name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return str(doc["seq"]).zfill(padding)

def _max_numeric_id(colname: str) -> int:
    """Read the highest numeric id currently stored (ids are '0001' strings)."""
    col = get_col(colname)
    doc = col.find({}, {"id": 1}).sort("id", -1).limit(1)
    doc = next(doc, None)
    if not doc or "id" not in doc: 
        return 0
    s = str(doc["id"]).lstrip("0") or "0"
    try:
        return int(s)
    except:
        return 0

def sync_counters():
    """Ensure counters start at current max for each collection."""
    db = get_db()
    for name in ("schools", "effects", "spells"):
        max_id = _max_numeric_id(name)
        db.counters.find_one_and_update(
            {"_id": name},
            {"$set": {"seq": max_id}},
            upsert=True
        )