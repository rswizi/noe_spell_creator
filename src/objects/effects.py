import json
import os
from dataclasses import dataclass, asdict


@dataclass
class Effect:
    id: str
    name: str
    school: str
    description: str
    en_cost: int = 0
    mp_cost: int = 0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def save(self, dir="effects"):
        safe_name = self.name.replace(" ", "_").lower()
        path = os.path.join("data", dir, f"{safe_name}.json")
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)


def load_effect(name, dir="effects"):
    safe_name = name.replace(" ", "_").lower()
    path = os.path.join("data", dir, f"{safe_name}.json")
    with open(path, "r") as f:
        data = json.load(f)
    return Effect.from_dict(data)
