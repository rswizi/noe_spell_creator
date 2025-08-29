import json
import os
from dataclasses import dataclass, asdict
from db_mongo import get_col


@dataclass
class School:
    id: str
    name: str
    school_type: str
    upgrade: bool
    range_type: str
    aoe_type: str

    def to_dict(self): return asdict(self)

    @classmethod
    def from_dict(cls, data): return cls(**data)

def load_school(id: str):
    doc = get_col("schools").find_one({"id": str(id)}, {"_id": 0})
    if not doc:
        raise FileNotFoundError(f"School {id} not found")
    # retro-compat
    if "upgrade" not in doc and "is_upgrade" in doc:
        doc["upgrade"] = bool(doc.pop("is_upgrade"))
    return School.from_dict(doc)


def load_school(id, dir="schools"):
    path = os.path.join("data", dir, f"{id}.json")
    with open(path, "r") as f:
        data = json.load(f)
    return School.from_dict(data)


def main():
    school = School(
        id = "0000",
        name = "School Test",
        school_type = "Simple",
        upgrade = False,
        range_type = "A",
        aoe_type = "A",
        )
    school.save()
    
if __name__ == "__main__":
    main()
