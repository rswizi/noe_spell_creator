import json
import os
from dataclasses import dataclass, asdict

from src.objects.schools import School, load_school


@dataclass
class Effect:
    id: str
    name: str
    school: School
    description: str
    en_cost: int = 0
    mp_cost: int = 0

    def to_dict(self):
        data = asdict(self)
        data["school"] = self.school.id
        return data

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def save(self, dir="effects"):
        path = os.path.join("data", dir, f"{self.id}.json")
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)


def load_effect(id, dir="effects"):
    path = os.path.join("data", dir, f"{id}.json")
    with open(path, "r") as f:
        data = json.load(f)
    data["school"] = load_school(data["school"])

    return Effect.from_dict(data)


def main():
    """"""
    effect = load_effect("0000")
    print(effect)


if __name__ == "__main__":
    main()
