import sys, os, hashlib
# add project root (one level up from /scripts) to import path
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from db_mongo import get_col

def sha(s): return hashlib.sha256(s.encode("utf-8")).hexdigest()

get_col("users").update_one(
    {"username": "wizi"},
    {"$set": {"username": "wizi", "password_hash": sha("YourPassword"), "role": "admin"}},
    upsert=True
)
print("seeded")
