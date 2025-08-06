import os
import json


def read( id):
    path = os.path.join("spells", f"{id}.json")

    with open(path, "r") as f:
        data = json.load(f)
        return data
       

class Spell:
    def __init__(self, id, name, en_cost, mp_cost, activation, range, aoe, duration, effects, schools, category, type):
        self.id = id
        self.name = name
        self.activation = activation
        self.mp_cost = mp_cost
        self.en_cost = en_cost
        self.range = range
        self.aoe = aoe
        self.duration = duration
        self.effects = effects
        self.schools = schools
        self.categoru = category
        self.type = type

    def __str__(self):
        return f"Name: {self.name} | MP Cost: {self.mp_cost}"
    
    def save(self):
        data = {
            "id": self.id,
            "name": self.name,
            "activation": self.activation,
            "mp_cost": self.mp_cost,
            "en_cost": self.en_cost,
            "range": self.range,
            "aoe": self.aoe,
            "duration": self.duration,
            "effects": self.effects,
            "schools": self.schools,
            "category": self.category,
            "type": self.type
        }

        path = os.path.join("spells", f"{self.id}.json")

        with open(path, "w") as f:
            json.dump(data, f, indent = 4)
    
    @classmethod
    def from_dict(cls, data):
        kwargs = {}
        for attr, default in cls._fields.items():
            json_key = default if isinstance(default, str) else attr
            if json_key not in data and not isinstance(default, (int, float, str, type(None))):
                raise ValueError(f"Missing required field '{json_key}'")
            kwargs[attr] = data.get(json_key, default)
        return cls(**kwargs)

data = read("0000")

spell = Spell.from_dict(data)

print(spell)