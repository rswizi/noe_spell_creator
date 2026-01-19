import json
import os
from dataclasses import dataclass, asdict, field
from typing import List
from db_mongo import get_col
from server.src.objects.schools import load_school, School


@dataclass
class Effect:
    id: str
    name: str
    school: School
    description: str = ""
    en_cost: int = 0
    mp_cost: int = 0
    skill_roll: bool = False
    skill_roll_skills: List[str] = field(default_factory=list)
    rolls: List[dict] = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        d["school"] = self.school.id
        return d

    @classmethod
    def from_dict(cls, d: dict):
        return cls(**d)

def load_effect(id: str) -> Effect:
    doc = get_col("effects").find_one({"id": str(id)}, {"_id": 0})
    if not doc:
        raise FileNotFoundError(f"Effect {id} not found in MongoDB")
    # normalize + coerce
    doc["school"] = load_school(str(doc.get("school")))
    for k in ("mp_cost", "en_cost"):
        try:
            doc[k] = int(doc.get(k, 0))
        except Exception:
            doc[k] = 0
    return Effect.from_dict(doc)

def main():
    """"""
    effect = load_effect("0000")
    print(effect)


if __name__ == "__main__":
    main()
