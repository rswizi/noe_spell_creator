from server.src.objects.effects import load_effect
from db_mongo import get_col
from server.src.objects.spells import Spell
from server.src.modules.category_table import category_for_mp
import re

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

    step = 1
    base = int(current_mp or 0)
    MAX_MP = base + 100_000  # sane cap
    hi = base + step
    while hi <= MAX_MP and category_for_mp(hi) == cur_cat:
        step *= 2
        hi = base + step
    if hi > MAX_MP:
        return 0

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

def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def _effect_duplicate_groups() -> list[dict]:
    """Group effects by normalized (name, description)."""
    eff_col = get_col("effects")
    docs = list(eff_col.find({}, {"_id": 0, "id": 1, "name": 1, "description": 1}))
    buckets: dict[tuple[str,str], list[dict]] = {}
    for e in docs:
        key = (_norm_text(e.get("name")), _norm_text(e.get("description")))
        buckets.setdefault(key, []).append(e)
    groups = []
    for (n, d), items in buckets.items():
        if len(items) > 1:
            ids = sorted(str(x["id"]) for x in items)
            groups.append({
                "name":      items[0].get("name", ""),
                "description": items[0].get("description", ""),
                "ids":       ids,
                "keep":      ids[0],
                "remove":    ids[1:],
                "count":     len(ids),
            })
    return groups

def _recompute_spells_for_school(school_id: str) -> tuple[str, int]:
    eff_col = get_col("effects")
    sp_col  = get_col("spells")

    eff_ids = [e["id"] for e in eff_col.find({"school": school_id}, {"_id":0,"id":1})]
    if not eff_ids:
        return (f"No effects belong to school [{school_id}].", 0)

    affected = list(sp_col.find({"effects": {"$in": eff_ids}}, {"_id": 0}))
    if not affected:
        return ("No spells referenced effects from this school.", 0)

    changed = 0
    lines: list[str] = [f"Recompute after School update [{school_id}]:", ""]

    for sp in affected:
        old_mp = int(sp.get("mp_cost", 0))
        old_en = int(sp.get("en_cost", 0))
        old_cat = sp.get("category", "")

        cc = compute_spell_costs(
            sp.get("activation","Action"),
            int(sp.get("range",0)),
            sp.get("aoe","A Square"),
            int(sp.get("duration",1)),
            [str(x) for x in (sp.get("effects") or [])]
        )

        new_mp, new_en, new_cat = cc["mp_cost"], cc["en_cost"], cc["category"]

        if (old_mp, old_en, old_cat) != (new_mp, new_en, new_cat):
            sp_col.update_one({"id": sp["id"]}, {"$set": {
                "mp_cost": new_mp,
                "en_cost": new_en,
                "category": new_cat
            }})
            changed += 1
            lines.append(
              f"[{sp['id']}] {sp.get('name','(unnamed)')}: "
              f"MP {old_mp} → {new_mp}, EN {old_en} → {new_en}, Category {old_cat} → {new_cat}"
            )

    if changed == 0:
        lines.append("No MP/EN/category changes after recompute.")
    return ("\n".join(lines), changed)

def _recompute_spells_for_effect(effect_id: str) -> tuple[str, int]:

    sp_col = get_col("spells")
    changed = 0
    lines: list[str] = []

    affected = list(sp_col.find({"effects": effect_id}, {"_id": 0}))
    if not affected:
        return ("No spells referenced this effect.", 0)

    for sp in affected:
        old_mp = int(sp.get("mp_cost", 0))
        old_en = int(sp.get("en_cost", 0))
        old_cat = sp.get("category", "")

        # recompute with current effect docs
        cc = compute_spell_costs(
            sp.get("activation", "Action"),
            int(sp.get("range", 0)),
            sp.get("aoe", "A Square"),
            int(sp.get("duration", 1)),
            [str(x) for x in (sp.get("effects") or [])]
        )

        new_mp, new_en, new_cat = cc["mp_cost"], cc["en_cost"], cc["category"]

        # Only write if something changed
        if (old_mp, old_en, old_cat) != (new_mp, new_en, new_cat):
            sp_col.update_one({"id": sp["id"]}, {"$set": {
                "mp_cost": new_mp,
                "en_cost": new_en,
                "category": new_cat
            }})
            changed += 1
            lines.append(
                f"[{sp['id']}] {sp.get('name','(unnamed)')}: "
                f"MP {old_mp} → {new_mp}, EN {old_en} → {new_en}, Category {old_cat} → {new_cat}"
            )

    if not lines:
        lines.append("No MP/EN/category changes after recompute.")
    return ("\n".join(lines), changed)