from dataclasses import dataclass, asdict
from typing import List, Union
from db_mongo import get_col
from server.src.modules.category_table import category_for_mp
from server.src.modules.cost_utils import (
    get_range_cost, get_aoe_cost, get_duration_cost, get_activation_cost, get_school_cost
)
from .effects import Effect

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
    def compute_cost(range_val, aoe_val, duration_val, activation_val, effects):
        mp_cost = en_cost = 0
        r_mp, r_en = Spell.norm(get_range_cost(range_val, effects))
        a_mp, a_en = Spell.norm(get_aoe_cost(aoe_val, effects))
        d_mp, d_en = Spell.norm(get_duration_cost(duration_val))
        act_mp, act_en = Spell.norm(get_activation_cost(activation_val))
        mp_cost += r_mp + a_mp + d_mp + act_mp
        en_cost += r_en + a_en + d_en + act_en
        for eff in effects:
            mp_cost += getattr(eff, "mp_cost", 0) or 0
            en_cost += getattr(eff, "en_cost", 0) or 0
        return mp_cost, en_cost

    def __post_init__(self):
        self.set_spell_type()
        self.update_cost()
        self.set_spell_category()

def load_spell(id: str) -> Spell:
    doc = get_col("spells").find_one({"id": str(id)}, {"_id": 0})
    if not doc:
        raise FileNotFoundError(f"Spell {id} not found in MongoDB")
    return Spell(**doc)
