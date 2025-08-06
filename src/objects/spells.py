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
    spell = load_spell("0000")
    print(spell.effects)


if __name__ == "__main__":
    main()
