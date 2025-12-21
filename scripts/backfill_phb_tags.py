# scripts/backfill_phb_tags.py
from db_mongo import get_db


def backfill(collection_name):
    col = get_db()[collection_name]
    filt = {
        "$or": [
            {"tags": {"$exists": False}},
            {"tags": []},
            {"tags": ""},
            {"tags": None},
        ]
    }
    res = col.update_many(filt, {"$set": {"tags": ["phb"]}})
    return res.modified_count


if __name__ == "__main__":
    targets = ["effects", "objects", "tools", "weapons", "equipment"]
    total = 0
    for name in targets:
        changed = backfill(name)
        total += changed
        print(f"{name}: updated {changed}")
    inv = get_db()["inventories"]
    inv_filt = {
        "items": {
            "$elemMatch": {
                "$or": [
                    {"tags": {"$exists": False}},
                    {"tags": []},
                    {"tags": ""},
                    {"tags": None},
                ]
            }
        }
    }
    inv_res = inv.update_many(inv_filt, {"$set": {"items.$[it].tags": ["phb"]}}, array_filters=[{
        "$or": [
            {"it.tags": {"$exists": False}},
            {"it.tags": []},
            {"it.tags": ""},
            {"it.tags": None},
        ]
    }])
    print(f"inventories.items: updated {inv_res.modified_count}")
    print(f"Total updated: {total + inv_res.modified_count}")
