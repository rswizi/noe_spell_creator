import os, json, sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)  # dossier "NoE Apps"
SCHOOLS_DIR = os.path.join(ROOT, "server", "data", "schools")

def main():
    if not os.path.isdir(SCHOOLS_DIR):
        print("Schools dir not found:", SCHOOLS_DIR)
        sys.exit(1)

    changed = 0
    for fn in os.listdir(SCHOOLS_DIR):
        if not fn.endswith(".json"): continue
        p = os.path.join(SCHOOLS_DIR, fn)
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "is_upgrade" in data:
                data["upgrade"] = bool(data.get("is_upgrade"))
                del data["is_upgrade"]
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                changed += 1
        except Exception as e:
            print("Error on", fn, "->", e)

    print(f"Done. Updated {changed} file(s).")

if __name__ == "__main__":
    main()
