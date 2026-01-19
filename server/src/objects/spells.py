from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import List, Union
from db_mongo import get_col
from server.src.modules.category_table import category_for_mp
from server.src.modules.cost_utils import (
    get_range_cost, get_aoe_cost, get_duration_cost, get_activation_cost, get_school_cost
)
from .effects import Effect
from typing import Iterable, Tuple, Dict, Any
from server.src.modules.cost_tables import (
    ACTIVATION_COSTS, RANGE_COSTS, AOE_COSTS, DURATION_COSTS
)
from server.src.modules.category_table import category_for_mp
from server.src.objects.schools import load_school

TYPE_ORDER = {"A": 1, "B": 2, "C": 3}

def _dominant_type(letters: Iterable[str]) -> str:
    best = "A"
    for lt in letters or []:
        up = str(lt or "A").strip().upper()[:1]
        if TYPE_ORDER.get(up, 1) > TYPE_ORDER[best]:
            best = up
    return best


def _coerce_school_id(school_field: Any) -> str | None:
    """
    Effects may carry a school id string or an object with .id.
    Return '0001'… or None.
    """
    if not school_field:
        return None
    if isinstance(school_field, str):
        return school_field
    return getattr(school_field, "id", None)

@dataclass
class Spell:
    id: str
    name: str
    activation: str
    range: int
    aoe: str
    duration: int
    category: str
    effects: List[Union[str, Effect]]
    effects_meta: List[dict] | None = None
    spell_type: str
    mp_cost: int
    en_cost: int
    description: str = ""

    def to_dict(self):
        d = asdict(self)
        d["effects"] = [e.id if isinstance(e, Effect) else str(e) for e in (self.effects or [])]
        d["mp_cost"]  = int(d.get("mp_cost", 0))
        d["en_cost"]  = int(d.get("en_cost", 0))
        d["range"]    = int(d.get("range", 0))
        d["duration"] = int(d.get("duration", 0))
        return d

    def save(self):
        get_col("spells").update_one({"id": self.id}, {"$set": self.to_dict()}, upsert=True)

    def set_spell_category(self):
        self.category = category_for_mp(self.mp_cost)

    def set_spell_type(self):
        # If any effect’s school is Complex → Complex, else Simple
        for e in self.effects:
            if isinstance(e, Effect) and getattr(e.school, "school_type", "").lower() == "complex":
                self.spell_type = "Complex"
                return
        self.spell_type = "Simple"

    def set_school_nbr(self):
        mp_school, _ = get_school_cost(self.effects, None)  # second arg unused by your util
        return mp_school + 1

    def set_range_cost(self):    return self.norm(get_range_cost(self.range, self.effects))[0]
    def set_aoe_cost(self):      return self.norm(get_aoe_cost(self.aoe, self.effects))[0]
    def set_duration_cost(self): return self.norm(get_duration_cost(self.duration))[0]
    def set_activation_cost(self): return self.norm(get_activation_cost(self.activation))[0]

    @staticmethod
    def norm(x):
        if isinstance(x, tuple):
            if len(x) == 2: return x
            if len(x) == 1: return (x[0], 0)
            return (x[0], x[1] if len(x) > 1 else 0)
        return (x or 0, 0)

    def update_cost(self):
        self.mp_cost, self.en_cost = Spell.compute_cost(
            self.range, self.aoe, self.duration, self.activation, self.effects
        )

    @staticmethod
    def compute_cost(
        range_val: int,
        aoe_val: str,
        duration_val: int,
        activation_val: str,
        effects: Iterable[Any],
    ) -> Tuple[int, int, Dict[str, Any]]:

        # ----- gather schools for type resolution -----
        school_objs = []
        for eff in (effects or []):
            sid = _coerce_school_id(getattr(eff, "school", None))
            if sid:
                try:
                    school_objs.append(load_school(sid))
                except Exception:
                    # fail-safe: skip if not found
                    pass

        range_type = _dominant_type([getattr(s, "range_type", "A") for s in school_objs])
        aoe_type   = _dominant_type([getattr(s, "aoe_type",   "A") for s in school_objs])

        # ----- knobs from tables -----
        try:
            act_mp, act_en = ACTIVATION_COSTS[activation_val]
        except KeyError:
            raise ValueError(f"Unknown activation '{activation_val}'")

        try:
            rng_mp, rng_en = RANGE_COSTS[range_type][int(range_val)]
        except KeyError:
            raise ValueError(f"Invalid range '{range_val}' for type '{range_type}'")

        try:
            aoe_mp, aoe_en = AOE_COSTS[aoe_type][aoe_val]
        except KeyError:
            raise ValueError(f"Invalid AoE '{aoe_val}' for type '{aoe_type}'")

        try:
            dur_mp, dur_en = DURATION_COSTS[int(duration_val)]
        except KeyError:
            raise ValueError(f"Invalid duration '{duration_val}'")

        # ----- effects -----
        eff_rows = []
        eff_mp = eff_en = 0
        for eff in (effects or []):
            e_mp = int(getattr(eff, "mp_cost", 0))
            e_en = int(getattr(eff, "en_cost", 0))
            eff_mp += e_mp
            eff_en += e_en
            eff_rows.append({
                "id":   getattr(eff, "id", ""),
                "name": getattr(eff, "name", ""),
                "mp":   e_mp,
                "en":   e_en,
                "school": _coerce_school_id(getattr(eff, "school", None)) or "",
            })

        # ----- school mix surcharge (non-upgrade schools only) -----
        non_upgrade_ids = []
        for s in school_objs:
            if not getattr(s, "upgrade", False):
                non_upgrade_ids.append(getattr(s, "id", None))
        distinct = len({sid for sid in non_upgrade_ids if sid})
        # At least 1 school; each extra non-upgrade school costs (+1 MP, +5 EN)
        extra_count = max(distinct, 1) - 1
        sch_mp, sch_en = 5 * extra_count, extra_count

        # ----- totals -----
        mp_total = act_mp + rng_mp + aoe_mp + dur_mp + eff_mp + sch_mp
        en_total = act_en + rng_en + aoe_en + dur_en + eff_en + sch_en

        breakdown = {
            "activation": {"mp": act_mp, "en": act_en},
            "range":      {"mp": rng_mp, "en": rng_en, "type": range_type},
            "aoe":        {"mp": aoe_mp, "en": aoe_en, "type": aoe_type},
            "duration":   {"mp": dur_mp, "en": dur_en},
            "effects":    eff_rows,
            "schools": {
                "distinct_non_upgrade": max(distinct, 1),
                "surcharge": {"mp": sch_mp, "en": sch_en},
            },
            "total": {"mp": mp_total, "en": en_total},
            "category": category_for_mp(mp_total),
        }
        return mp_total, en_total, breakdown


def load_spell(id: str) -> Spell:
    doc = get_col("spells").find_one({"id": str(id)}, {"_id": 0})
    if not doc:
        raise FileNotFoundError(f"Spell {id} not found in MongoDB")
    return Spell(**doc)
