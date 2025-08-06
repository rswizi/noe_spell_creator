import json
import os
from dataclasses import dataclass, asdict, field


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
    effects: list = field(default_factory=list)
    schools: list = field(default_factory=list)
    category: str = "Novice"
    spell_type: str = "Simple"

    def __str__(self):
        return f"Name: {self.name} | MP Cost: {self.mp_cost}"

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def save(self, dir="spells"):
        data = self.to_dict()
        path = os.path.join(dir, f"{self.id}.json")

        with open(path, "w") as f:
            json.dump(data, f, indent=2)


def load_spell(id, dir="spells"):
    path = os.path.join(dir, f"{id}.json")
    with open(path, "r") as f:
        data = json.load(f)

    return Spell.from_dict(data)


def main():
    """"""
    spell = load_spell("0000")
    print(spell)


if __name__ == "__main__":
    main()
