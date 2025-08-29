from collections import Counter
from server.src.modules.cost_tables import (
    RANGE_COSTS,
    AOE_COSTS,
    DURATION_COSTS,
    ACTIVATION_COSTS
)

def get_range_cost(range_val, effects, range_table=RANGE_COSTS):
    range_type = "A"
    for effect in effects:
        rt = getattr(effect, "range_type", "A")
        if rt == "C":
            range_type = "C"
            break
        elif rt == "B":
            range_type = "B"
    try:
        return range_table[range_type][range_val]
    except KeyError:
        raise ValueError(f"Invalid Range value '{range_val}' for range type '{range_type}'")

def get_aoe_cost(aoe_val, effects, aoe_table=AOE_COSTS):
    aoe_type = "A"
    for effect in effects:
        at = getattr(effect, "aoe_type", "A")
        if at == "C":
            aoe_type = "C"
            break
        elif at == "B":
            aoe_type = "B"
    try:
        return aoe_table[aoe_type][aoe_val]
    except KeyError:
        raise ValueError(f"Invalid AoE value '{aoe_val}' for AoE type '{aoe_type}'")

def get_duration_cost(duration_val, duration_table=DURATION_COSTS):
    try:
        return duration_table[duration_val]
    except KeyError:
        raise ValueError(f"Invalid Duration value '{duration_val}'")

def get_activation_cost(activation_val, activation_table=ACTIVATION_COSTS):
    try:
        return activation_table[activation_val]
    except KeyError:
        raise ValueError(f"Invalid Activation value '{activation_val}'")

def get_school_cost(effects, school_loader):
    filtered_ids = [
        effect.school.id for effect in effects
        if not school_loader(effect.school.id).upgrade
    ]
    school_count = max(len(dict(Counter(filtered_ids))), 1)
    return (school_count - 1, 5 * (school_count - 1))
