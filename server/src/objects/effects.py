import json
import os
from dataclasses import dataclass, asdict
from db_mongo import get_col
from server.src.objects.schools import load_school, School


@dataclass
class Effect:
    id: str
    name: str
    school: School
    description: str
    en_cost: int = 0
    mp_cost: int = 0

    def to_dict(self):
        d = asdict(self)
        d["school"] = self.school.id
        return d

    @classmethod
    def from_dict(cls, data): return cls(**data)

def load_effect(id: str):
    doc = get_col("effects").find_one({"id": str(id)}, {"_id": 0})
    if not doc:
        raise FileNotFoundError(f"Effect {id} not found")
    doc["school"] = load_school(doc["school"])
    return Effect.from_dict(doc)


def main():
    """"""
    effect = load_effect("0000")
    print(effect)


if __name__ == "__main__":
    main()
