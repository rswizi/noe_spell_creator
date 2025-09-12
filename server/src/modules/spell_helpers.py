from server.src.objects.effects import load_effect
from db_mongo import get_col
from server.src.objects.spells import Spell
from server.src.modules.category_table import category_for_mp
from server.src.modules.cost_tables import ACTIVATION_COSTS, RANGE_COSTS, AOE_COSTS, DURATION_COSTS
import re

TYPE_ORDER = {"A": 1, "B": 2, "C": 3}

def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def _pick_max_type(types):
    best = "A"
    for t in (types or []):
        tt = (t or "A").upper()
        if TYPE_ORDER.get(tt, 1) > TYPE_ORDER.get(best, 1):
            best = tt
    return best

def _derive_types_from_effects(effect_ids):
    # Look up schools of selected effects; choose the max A/B/C across them.
    eff_col = get_col("effects")
    sch_col = get_col("schools")
    effs = list(eff_col.find({"id": {"$in": [str(e) for e in (effect_ids or [])]}} , {"_id":0,"school":1}))
    sch_ids = sorted({ str(e.get("school","")) for e in effs if e.get("school") })
    if not sch_ids:
        return ("A", "A")
    # fetch only needed fields
    sch_docs = list(sch_col.find({"id": {"$in": sch_ids}}, {"_id":0,"id":1,"range_type":1,"aoe_type":1}))
    r_types = [ (s.get("range_type") or "A").upper() for s in sch_docs ]
    a_types = [ (s.get("aoe_type") or "A").upper()   for s in sch_docs ]
    return (_pick_max_type(r_types), _pick_max_type(a_types))

def _sum_effect_costs(effect_ids):
    """Return (mp_sum, en_sum). Pulls minimal fields if load_effect is unavailable."""
    mp_sum = 0
    en_sum = 0
    try:
        # Preferred path: use object loader (may include other metadata)
        for eid in (effect_ids or []):
            ef = load_effect(str(eid))
            mp_sum += int(getattr(ef, "mp_cost", 0) or 0)
            en_sum += int(getattr(ef, "en_cost", 0) or 0)
        return mp_sum, en_sum
    except Exception:
        # Fallback: read from DB
        docs = list(
            get_col("effects").find(
                {"id": {"$in": [str(eid) for eid in (effect_ids or [])]}},
                {"_id": 0, "mp_cost": 1, "en_cost": 1},
            )
        )
        for d in docs:
            mp_sum += int(d.get("mp_cost", 0) or 0)
            en_sum += int(d.get("en_cost", 0) or 0)
        return mp_sum, en_sum

def compute_spell_costs(
    activation: str,
    range_val: int,
    aoe: str,
    duration: int,
    effect_ids: list[str],
    *,
    range_type: str | None = None,
    aoe_type: str | None = None,
) -> dict:
    # 1) Decide cost table types
    if not range_type or range_type.upper() not in ("A","B","C"):
        rt, at = _derive_types_from_effects(effect_ids)
    else:
        rt = range_type.upper()
        at = (aoe_type or "A").upper() if aoe_type else _derive_types_from_effects(effect_ids)[1]

    # 2) Sum effect costs
    eff_mp, eff_en = _sum_effect_costs(effect_ids)

    # 3) Knob costs (tables)
    act_mp, act_en = ACTIVATION_COSTS.get(activation, (0,0))
    rng_mp, rng_en = RANGE_COSTS.get(rt, RANGE_COSTS["A"]).get(int(range_val), (0,0))
    aoe_mp, aoe_en = AOE_COSTS.get(at, AOE_COSTS["A"]).get(str(aoe), (0,0))
    dur_mp, dur_en = DURATION_COSTS.get(int(duration), (0,0))

    mp_cost = eff_mp + act_mp + rng_mp + aoe_mp + dur_mp
    en_cost = eff_en + act_en + rng_en + aoe_en + dur_en

    breakdown = {
        "activation": {"mp": act_mp, "en": act_en},
        "range":      {"mp": rng_mp, "en": rng_en, "type": rt},
        "aoe":        {"mp": aoe_mp, "en": aoe_en, "type": at},
        "duration":   {"mp": dur_mp, "en": dur_en},
        "effects":    {"mp": eff_mp, "en": eff_en},
    }

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
    MAX_MP = base + 100_000
    hi = base + step
    while hi <= MAX_MP and category_for_mp(hi) == cur_cat:
        step *= 2
        hi = base + step
    if hi > MAX_MP: return 0
    lo = max(base, hi - step)
    ans = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if category_for_mp(mid) == cur_cat:
            lo = mid + 1
        else:
            ans = mid
            hi = mid - 1
    return 0 if ans is None else max(0, ans - base)

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