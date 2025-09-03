from server.src.objects.effects import load_effect
from db_mongo import get_col
from server.src.objects.spells import Spell
from server.src.modules.category_table import category_for_mp

def compute_spell_costs(
    activation: str, range_val: int, aoe: str, duration: int, effect_ids: list[str]
) -> dict:
    try:
        effects = [load_effect(str(eid)) for eid in (effect_ids or [])]
    except Exception:
        docs = list(
            get_col("effects").find(
                {"id": {"$in": [str(eid) for eid in (effect_ids or [])]}},
                {"_id": 0, "mp_cost": 1, "en_cost": 1},
            )
        )
        class _E:
            def __init__(self, mp, en):
                self.mp_cost = int(mp or 0)
                self.en_cost = int(en or 0)
        effects = [_E(d.get("mp_cost", 0), d.get("en_cost", 0)) for d in docs]

    mp_cost, en_cost, breakdown = Spell.compute_cost(
        range_val, aoe, duration, activation, effects
    )

    return {
        "mp_cost": mp_cost,
        "en_cost": en_cost,
        "category": category_for_mp(mp_cost),
        "mp_to_next_category": mp_to_next_category_delta(mp_cost),
        "breakdown": breakdown,
    }

def mp_to_next_category_delta(current_mp: int) -> int:
    cur_cat = category_for_mp(int(current_mp or 0))

    # Exponential search to find an upper bound where category changes
    step = 1
    base = int(current_mp or 0)
    MAX_MP = base + 100_000  # sane cap
    hi = base + step
    while hi <= MAX_MP and category_for_mp(hi) == cur_cat:
        step *= 2
        hi = base + step
    if hi > MAX_MP:
        # couldn't find a higher category within cap -> treat as top category
        return 0

    # Binary search for first MP where category changes
    lo = max(base, hi - step)
    ans = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if category_for_mp(mid) == cur_cat:
            lo = mid + 1
        else:
            ans = mid
            hi = mid - 1

    if ans is None:
        return 0
    return max(0, ans - base)