import json
import os
from dataclasses import dataclass, asdict
from db_mongo import get_col


@dataclass
class School:
    id: str
    name: str
    school_type: str = "Simple"
    upgrade: bool = False
    range_type: str = "A"
    aoe_type: str = "A"
    cost_mode: str = "en"

    def to_dict(self): 
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict):
        # retro-compat for older dumps
        if "upgrade" not in d and "is_upgrade" in d:
            d["upgrade"] = bool(d.pop("is_upgrade"))
        if "cost_mode" not in d:
            d["cost_mode"] = "en"
        return cls(**d)

def load_school(id: str) -> School:
    doc = get_col("schools").find_one({"id": str(id)}, {"_id": 0})
    if not doc:
        raise FileNotFoundError(f"School {id} not found in MongoDB")
    return School.from_dict(doc)

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
