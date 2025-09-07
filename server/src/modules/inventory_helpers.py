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