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


def load_effect(name, dir="effects"):
    safe_name = name.replace(" ", "_").lower()
    path = os.path.join("data", dir, f"{safe_name}.json")
    with open(path, "r") as f:
        data = json.load(f)
    return Effect.from_dict(data)


def main():
    """"""
    school = load_school("0000")
    effect = Effect(
        id = "0000",
        name = "Test",
        school = school,
        description = "test",
        en_cost = 5,
        mp_cost = 6,
    )
    print(effect)
    effect.save()


if __name__ == "__main__":
    main()
