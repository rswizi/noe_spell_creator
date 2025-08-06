import json
import os
from dataclasses import dataclass, asdict


@dataclass
class School:
    id: str
    name: str
    school_type: str
    upgrade: str
    range_type: str
    aoe_type: str

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def save(self, dir="schools"):
        path = os.path.join("data", dir, f"{self.id}.json")
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)


def load_school(id, dir="schools"):
    path = os.path.join("data", dir, f"{id}.json")
    with open(path, "r") as f:
        data = json.load(f)
    return School.from_dict(data)
