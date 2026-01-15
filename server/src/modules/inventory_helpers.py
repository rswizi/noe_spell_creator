QDIFF = {
    "Mediocre": -100, "Adequate": 0, "Good": 167, "Very Good": 1390,
    "Excellent": 5280, "Legendary": 15300, "Mythical": 38760,
    "Epic": 128000, "Divine": 614400, "Unreal": 921600,
}
SLOTS = { "Adequate":1,"Good":2,"Very Good":3,"Excellent":4,"Legendary":5,"Mythical":6,"Epic":7,"Divine":8,"Unreal":9 }

UPGRADE_STEPS = [
    {"n":1, "hours":1,   "dc":7,  "fee":7},
    {"n":2, "hours":2,   "dc":8,  "fee":14},
    {"n":3, "hours":4,   "dc":10, "fee":28},
    {"n":4, "hours":8,   "dc":13, "fee":200},
    {"n":5, "hours":16,  "dc":15, "fee":400},
    {"n":6, "hours":32,  "dc":23, "fee":1440},
    {"n":7, "hours":64,  "dc":25, "fee":3968},
    {"n":8, "hours":128, "dc":30, "fee":10240},
    {"n":9, "hours":300, "dc":25, "fee":30000},
]

WEAPON_UPGRADES = [
    {"key":"lethality","name":"Lethality","unique":False},
    {"key":"increase","name":"Increase","unique":False},
    {"key":"acuity","name":"[Unique] Acuity","unique":True},
    {"key":"rune","name":"[Unique] Rune","unique":True},
    {"key":"magazine","name":"Magazine","unique":False},
    {"key":"silver","name":"[Unique] Silver Plating","unique":True},
    {"key":"range","name":"Range","unique":False},
    {"key":"blessing","name":"Blessing","unique":False},
    {"key":"defense","name":"[Unique] Defense","unique":True},
]
ARMOR_UPGRADES = [
    {"key":"defense","name":"Defense (+12 HP)","unique":False},
    {"key":"enchant","name":"Enchantement (+1 EN +1 FO)","unique":False},
]

def _slots_for_quality(q: str) -> int:
    return SLOTS.get(q, 0)

def _qprice(base: int, q: str) -> int:
    return max(0, int(base or 0) + int(QDIFF.get(q, 0)))

def _upgrade_fee_for_range(start_count: int, add: int) -> tuple[int, list[dict]]:
    """Sum fees for adding `add` upgrades when you already have `start_count`."""
    total = 0; steps = []
    for k in range(start_count+1, start_count+add+1):
        st = next((s for s in UPGRADE_STEPS if s["n"]==k), None)
        if not st: continue
        total += st["fee"]; steps.append(st)
    return total, steps

QUALITY_ORDER = ["Adequate","Good","Very Good","Excellent","Legendary","Mythical","Epic","Divine","Unreal"]

def _compose_variant(quality: str | None, upgrades: list | None) -> str:
    q = (quality or "Adequate")
    n = len(upgrades or [])
    return f"{q} +{n}upg"

def _pick_currency(inv: dict, preferred: str | None = None) -> str:
    if preferred: 
        return preferred
    cur = inv.get("currencies") or {}
    if cur:
        # return the first key deterministically
        return sorted(cur.keys())[0]
    return "Jelly"

CRAFTOMANCY_CATEGORY_ORDER = [
    "Novice", "Apprentice", "Disciple", "Adept", "Mage", "Magister",
    "High Mage", "Master", "Grand Master", "Archmage", "Supreme Archmage", "Avant-Garde"
]
CRAFTOMANCY_TABLE = {
    "Very Mediocre": {"category": "Novice", "skill": 5, "die": "d4", "dc": 3, "price": 200, "hours": 10},
    "Mediocre": {"category": "Apprentice", "skill": 6, "die": "d4", "dc": 5, "price": 300, "hours": 15},
    "Adequate": {"category": "Disciple", "skill": 7, "die": "d4", "dc": 7, "price": 400, "hours": 20},
    "Good": {"category": "Adept", "skill": 8, "die": "d6", "dc": 8, "price": 500, "hours": 25},
    "Very Good": {"category": "Mage", "skill": 9, "die": "d6", "dc": 10, "price": 750, "hours": 30},
    "Excellent": {"category": "Magister", "skill": 10, "die": "d8", "dc": 13, "price": 875, "hours": 35},
    "Legendary": {"category": "High Mage", "skill": 11, "die": "d8", "dc": 15, "price": 1600, "hours": 40},
    "Mythical": {"category": "Master", "skill": 12, "die": "d10", "dc": 23, "price": 2500, "hours": 50},
    "Epic": {"category": "Grand Master", "skill": 13, "die": "d10", "dc": 25, "price": 6000, "hours": 60},
    "Divine": {"category": "Archmage", "skill": 14, "die": "d12", "dc": 30, "price": 14000, "hours": 70},
    "Unreal": {"category": "Supreme Archmage", "skill": 15, "die": "d12", "dc": 25, "price": 32000, "hours": 80},
}

def craftomancy_row_for_quality(q: str | None) -> dict:
    key = (q or "Adequate").strip()
    return dict(CRAFTOMANCY_TABLE.get(key) or CRAFTOMANCY_TABLE["Adequate"])

def craftomancy_category_index(cat: str | None) -> int:
    c = (cat or "").strip()
    if not c:
        return -1
    try:
        return CRAFTOMANCY_CATEGORY_ORDER.index(c)
    except ValueError:
        return -1

def craftomancy_next_category(cat: str | None) -> str | None:
    idx = craftomancy_category_index(cat)
    if idx < 0 or idx + 1 >= len(CRAFTOMANCY_CATEGORY_ORDER):
        return None
    return CRAFTOMANCY_CATEGORY_ORDER[idx + 1]
