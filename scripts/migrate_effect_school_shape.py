# scripts/migrate_effect_school_shape.py
import os, json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EFFECTS_DIR = os.path.join(BASE_DIR, "..", "server", "data", "effects")  # adjust path if needed

changed, skipped = 0, 0

for fname in os.listdir(EFFECTS_DIR):
    if not fname.endswith(".json"):
        continue
    path = os.path.join(EFFECTS_DIR, fname)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        sch = data.get("school")
        if isinstance(sch, dict) and "id" in sch:
            data["school"] = sch["id"]       # convert to string id
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            changed += 1
        else:
            skipped += 1
    except Exception as e:
        print(f"Error migrating {path}: {e}")

print(f"Done. Changed: {changed}, unchanged/skipped: {skipped}")