import os
import json

class Effect:
    def __init__(self, name, school, description, en_cost, mp_cost, school_type, upgrade, range_type, aoe_type):
        self.name = name
        self.school = school
        self.description = description
        self.en_cost = en_cost
        self.mp_cost = mp_cost
        self.school_type = school_type
        self.upgrade = upgrade
        self.range_type = range_type
        self.aoe_type = aoe_type