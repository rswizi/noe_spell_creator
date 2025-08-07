import json
import os
from dataclasses import dataclass, asdict, field
from collections import Counter


from src.objects.effects import Effect, load_effect
from src.objects.schools import load_school
from src.modules.cost_tables import RANGE_COSTS, AOE_COSTS, DURATION_COSTS, ACTIVATION_COSTS


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
        filtered_ids = []
        for effect in self.effects:
            school = load_school(effect.school.id)
            if not school.upgrade:
                filtered_ids.append(effect.school.id)
        return max(len(dict(Counter(filtered_ids))),1)

    def set_range_cost(self):
        range_type ="A"
        for effect in self.effects:
            rt = getattr(effect, "range_type", "A")
            if rt == "C":
                range_type = "C"
                break
            elif rt == "B":
                range_type = "B"
        range_table = RANGE_COSTS
        
        try:
            mp_cost, en_cost = range_table[range_type][self.range]
        except KeyError:
            raise ValueError(f"Invalid Range valyue '{self.range}' for range type '{range_type}'")
        return mp_cost, en_cost
    
    def set_aoe_cost(self):
        aoe_type = "A"
        for effect in self.effects:
            at= getattr(effect, "aoe_type", "A")
            if at == "C":
                aoe_type = "C"
                break
            elif at == "B":
                aoe_type = "B"
        aoe_table = AOE_COSTS

        try:
            mp_cost, en_cost = aoe_table[aoe_type][self.aoe]
        except KeyError:
            raise ValueError(f"Invalid AoE value '{self.aoe}' for range type '{aoe_type}'")
        return mp_cost, en_cost
    
    def set_duration_cost(self):
        duration_table = DURATION_COSTS
        mp_cost, en_cost = duration_table[self.duration]
        return mp_cost, en_cost
    
    def set_activation_cost(self):
        activation_tale = ACTIVATION_COSTS
        mp_cost, en_cost = activation_tale[self.activation]
        return mp_cost, en_cost
    
    def update_cost(self):
        mp_range_cost, en_range_cost = self.set_range_cost()
        mp_aoe_cost, en_aoe_cost = self.set_aoe_cost()
        mp_duration_cost, en_duration_cost = self.set_duration_cost()
        mp_school_nbr_cost, en_school_nbr_cost = self.set_school_nbr()-1, 5*(self.set_school_nbr()-1)
        mp_activation_cost, en_activation_cost = self.set_activation_cost()

        self.mp_cost = sum(effects.mp_cost for effects in self.effects) + mp_school_nbr_cost + mp_range_cost + mp_aoe_cost + mp_duration_cost + mp_activation_cost
        self.en_cost = sum(effects.en_cost for effects in self.effects) + en_school_nbr_cost + en_range_cost + en_aoe_cost + en_duration_cost + en_activation_cost

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
            f"Effect IDs: {[effect.id for effect in self.effects]}"
        )
    
    def to_dict(self):
        effect_ids = []
        for effect in self.effects:
            effect_ids.append(effect.id)
        data = asdict(self)
        data["effects"] = effect_ids
        return data

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def save(self, dir="spells"):
        data = self.to_dict()
        path = os.path.join("data", dir, f"{self.id}.json")

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    def __post_init__(self):
        self.set_spell_category()
        self.set_spell_type()
        self.update_cost()


def load_spell(id, dir="spells"):

    path = os.path.join("data", dir, f"{id}.json")
    with open(path, "r") as f:
        data = json.load(f)
    effect_list = []
    for id in data["effects"]:
        effect_list.append(load_effect(id))
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
