import json
import os
from dataclasses import dataclass, asdict, field

from src.objects.effects import Effect, load_effect


@dataclass
class Spell:
    id: str
    name: str
    activation: str
    range: int
    aoe: str
    mp_cost: int = 0
    en_cost: int = 0
    duration: int = 0
    effects: list[Effect] = field(default_factory=list)
    category: str = "Novice"
    spell_type: str = "Simple"

    def __post_init__(self):
        # Costs
        self.en_cost = sum(effects.en_cost for effects in self.effects)
        self.mp_cost = sum(effects.mp_cost for effects in self.effects)

        # Catergory
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

    def __str__(self):
        return f"Name: {self.name} | MP Cost: {self.mp_cost}"
    
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
        range = "5",
        aoe = "Circle 5",
        effects = [Effect("0000", "Test 1", "0000", "Do some shit", 4, 45), Effect("0000", "Test 1", "0000", "Do some shit", 16, 4)]
    )
    print(spell.en_cost)
    print(spell.mp_cost)
    print(spell.category)

if __name__ == "__main__":
    main()
