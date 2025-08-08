import json
import os
from dataclasses import dataclass, asdict, field
from collections import Counter

from src.objects.effects import Effect, load_effect
from src.objects.schools import load_school
from src.modules.cost_utils import (
    get_range_cost,
    get_aoe_cost,
    get_duration_cost,
    get_activation_cost,
    get_school_cost
)

@dataclass
class Spell:
    id: str
    name: str
    activation: str
    range: int
    aoe: str
    mp_cost: int = 0
    en_cost: int = 0
    duration: int = 1
    effects: list[Effect] = field(default_factory=list)
    category: str = "Novice"
    spell_type: str = "Simple"
    description: str = "None"

    def save(self, dir="spells"):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(base_dir, "..", "..", "data", dir)
        os.makedirs(data_dir, exist_ok=True)

        path = os.path.join(data_dir, f"{self.id}.json")
        data = self.to_dict()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def set_spell_category(self):
        if self.mp_cost <= 12:
            self.category = "Novice"
        elif self.mp_cost <= 17:
            self.category = "Apprentice"
        elif self.mp_cost <= 22:
            self.category = "Disciple"
        elif self.mp_cost <= 27:
            self.category = "Adept"
        elif self.mp_cost <= 32:
            self.category = "Mage"
        elif self.mp_cost <= 37:
            self.category = "Magister"
        elif self.mp_cost <= 42:
            self.category = "High Mage"
        elif self.mp_cost <= 52:
            self.category = "Master"
        elif self.mp_cost <= 62:
            self.category = "Grand Master"
        elif self.mp_cost <= 75:
            self.category = "Archmage"
        elif self.mp_cost <= 85:
            self.category = "Supreme Archmage"
        else:
            self.category = "Avant-garde"
        
    def set_spell_type(self):
        for effect in self.effects:
            school = load_school(effect.school.id)
            if school.school_type.lower() == "complex":
                self.spell_type = "Complex"
                return
        self.spell_type = "Simple"

    def set_school_nbr(self):
        mp_school, _ = get_school_cost(self.effects, load_school)
        return mp_school + 1

    def set_range_cost(self):
        return get_range_cost(self.range, self.effects)

    def set_aoe_cost(self):
        return get_aoe_cost(self.aoe, self.effects)

    def set_duration_cost(self):
        return get_duration_cost(self.duration)

    def set_activation_cost(self):
        return get_activation_cost(self.activation)

    def update_cost(self):
        self.mp_cost, self.en_cost = Spell.compute_cost(
            self.range,
            self.aoe,
            self.duration,
            self.activation,
            self.effects,
            load_school
        )

    @staticmethod
    def compute_cost(range_val, aoe_val, duration_val, activation_val, effects):
        mp_cost = 0
        en_cost = 0

        # Example cost tables (replace with real ones)
        mp_cost += get_range_cost(range_val)
        mp_cost += get_aoe_cost(aoe_val)
        mp_cost += get_duration_cost(duration_val)
        mp_cost += get_activation_cost(activation_val)

        # If effects are provided, add their cost
        for effect in effects:
            mp_cost += effect.mp_cost
            en_cost += effect.en_cost

        return mp_cost, en_cost

    def __str__(self):
        return (
            f"Spell ID: {self.id}\n"
            f"Name: {self.name}\n"
            f"Activation: {self.activation}\n"
            f"Range: {self.range}\n"
            f"AoE: {self.aoe}\n"
            f"Duration: {self.duration}\n"
            f"MP Cost: {self.mp_cost}\n"
            f"EN Cost: {self.en_cost}\n"
            f"Category: {self.category}\n"
            f"Spell Type: {self.spell_type}\n"
            f"Number of Effects: {len(self.effects)}\n"
            f"Effect IDs: {[effect.id for effect in self.effects]}\n"
            f"Description: {self.description}"
        )

    def to_dict(self):
        data = asdict(self)
        data["effects"] = [effect.id for effect in self.effects]
        return data

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def __post_init__(self):
        self.set_spell_type()
        self.update_cost()
        self.set_spell_category()


def load_spell(id, dir="spells"):
    base_dir = os.path.dirname(os.path.abspath(__file__))  # src/objects
    data_dir = os.path.join(base_dir, "..", "..", "data", dir)
    path = os.path.join(data_dir, f"{id}.json")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    effect_list = [load_effect(eid) for eid in data["effects"]]
    data["effects"] = effect_list
    return Spell.from_dict(data)

def main():
    """"""

    spell = Spell(
        id = "0000",
        name = "Test 1",
        activation = "Action",
        range = 5,
        aoe = "Circle (5)",
        effects = [load_effect("0001"), load_effect("0000")]
    )
    
    print(spell)

    spell.save()

if __name__ == "__main__":
    main()