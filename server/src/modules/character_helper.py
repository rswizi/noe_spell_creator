# app/core/character_rules.py
from __future__ import annotations
from dataclasses import dataclass
from math import ceil, floor, isfinite, sqrt
from typing import Dict, Iterable, List, Tuple

# ----------------------------
# Level / XP
# ----------------------------

def xp_to_next_level(level: int) -> int:
    """XP required to go from `level` to `level+1` (level starts at 1)."""
    level = max(1, min(level, 100))
    return level * 100

def total_xp_for_level(level: int) -> int:
    """Cumulative XP required to *reach* a level (level 1 => 0 XP)."""
    level = max(1, min(level, 100))
    n = level - 1
    return 100 * n * (n + 1) // 2

def level_from_total_xp(xp_total: int) -> int:
    """Derive level from total XP using the closed form of the triangular sum."""
    xp_total = max(0, int(xp_total))
    # 100 * n(n+1)/2 <= xp_total  =>  n^2 + n - (xp_total/50) <= 0
    disc = 1 + 4 * (xp_total / 50)
    n = int(floor((-1 + sqrt(disc)) / 2.0))
    level = max(1, min(n + 1, 100))
    return level

# ----------------------------
# Caps
# ----------------------------

def max_skill_cap(level: int) -> int:
    """Maximum *invested* points in a skill (mods/char mods not included)."""
    if level >= 50: return 8
    if level >= 40: return 7
    if level >= 30: return 6
    if level >= 20: return 5
    if level >= 10: return 4
    return 3

def max_characteristic_cap(level: int) -> int:
    """Maximum *invested* points in a characteristic (mods not included)."""
    if level >= 55: return 10
    if level >= 46: return 9
    if level >= 37: return 8
    if level >= 28: return 7
    if level >= 19: return 6
    if level >= 10: return 5
    return 4

# ----------------------------
# Characteristics & Skills
# ----------------------------

MILESTONE_THRESHOLDS: Tuple[int, ...] = (4, 6, 8, 10, 12, 14, 16)

def characteristic_total(points_invested: int, char_mod: int = 0) -> int:
    """
    Total = invested + modifier (mods default 0 unless Sublimations/gear later).
    """
    return int(points_invested) + int(char_mod)

def characteristic_mod(total_value: int) -> int:
    """Mod = floor((Total - 10) / 2)"""
    return floor((int(total_value) - 10) / 2)

def milestones(total_value: int) -> int:
    """Count how many milestone thresholds are reached by this characteristic."""
    v = int(total_value)
    return sum(1 for t in MILESTONE_THRESHOLDS if v >= t)

def skill_base_value(
    skill_points: int,
    linked_characteristic_mod: int,
    skill_mod: int = 0,
    cap_mod_to_invested: bool = True
) -> int:
    """
    Base Value = Skill Invested + Skill Modifier + Linked Characteristic Mod.
    If cap_mod_to_invested=True, clamp skill_mod <= skill_points (your earlier rule).
    """
    sp = int(skill_points)
    sm = int(skill_mod)
    if cap_mod_to_invested:
        sm = min(sm, sp)
    return sp + sm + int(linked_characteristic_mod)

# ----------------------------
# Derived Resources
# ----------------------------

@dataclass
class Derived:
    hp_max: int
    sp_max: int
    en_max: int
    fo_max: int
    mo: int
    et: int
    tx_max: int
    encumbrance_max: int
    condition_dc: int
    sublimation_slots_max: int

def derived_resources(
    *,
    level: int,
    # milestones by characteristic name (computed from total values):
    mile_BOD: int,
    mile_WIL: int,
    mile_MAG: int,
    mile_PRE: int,
    mile_DEX: int,
    mile_REF: int,
    # required skill *base values* (already include linked characteristic mod):
    bv_athletics: int,
    bv_spirit: int,
    bv_resistance: int,
    bv_alchemy: int,
    # optional: extra bonuses from Sublimations (all default to 0 here)
    bonus_hp_flat: int = 0,            # e.g., Defense (+12 per tier) can be folded here
    bonus_en_flat: int = 0,            # e.g., Endurance (+2 per tier)
    bonus_fo_flat: int = 0,            # e.g., Clarity (+1 per tier)
    bonus_mo_flat: int = 0,            # e.g., Speed (+1 per tier)
) -> Derived:
    lvl = max(1, min(int(level), 100))
    lvl5 = lvl // 5
    lvl10 = lvl // 10

    # HP
    hp_max = 100 + (lvl - 1) + 12 * mile_BOD + 6 * mile_WIL + int(bonus_hp_flat)

    # EN
    en_max = 5 + lvl5 + mile_WIL + 2 * mile_MAG + int(bonus_en_flat)

    # FO
    fo_max = 2 + lvl5 + mile_WIL + mile_PRE + int(bonus_fo_flat)

    # MO
    mo = 4 + mile_DEX + mile_REF + int(bonus_mo_flat)

    # SP max (10% of HP, round down)
    sp_max = hp_max // 10

    # Encumbrance (per your simplified rule in this step)
    enc_max = 10 + int(bv_athletics) + int(bv_spirit)

    # ET
    et = 1 + lvl10 + mile_MAG

    # TX
    tx_max = int(bv_resistance) + int(bv_alchemy)

    # Condition DC
    condition_dc = 6 + lvl10

    # Sublimation slots
    sublimation_max = (2 * mile_PRE) + lvl10

    return Derived(
        hp_max=hp_max,
        sp_max=sp_max,
        en_max=en_max,
        fo_max=fo_max,
        mo=mo,
        et=et,
        tx_max=tx_max,
        encumbrance_max=enc_max,
        condition_dc=condition_dc,
        sublimation_slots_max=sublimation_max,
    )

# ----------------------------
# Convenience: compute full bundle
# ----------------------------

@dataclass
class CharacterInput:
    level: int
    invested_characteristics: Dict[str, int]      # e.g., {"BOD": 6, "WIL": 5, ...}
    characteristic_mods: Dict[str, int] | None    # external mods; default all 0
    invested_skills: Dict[str, int]               # e.g., {"Athletics": 3, "Spirit": 2, ...}
    skill_mods: Dict[str, int] | None             # external mods; default all 0
    # map a skill to its linked characteristic key (e.g., "Athletics" -> "BOD")
    skill_links: Dict[str, str]

@dataclass
class CharacterComputed:
    level: int
    total_xp_for_level: int
    next_level_xp_cost: int
    characteristic_totals: Dict[str, int]
    characteristic_mods: Dict[str, int]   # computed from totals (floor((V-10)/2))
    milestones: Dict[str, int]
    skill_base_values: Dict[str, int]
    caps: Dict[str, int]
    derived: Derived

def compute_character(ci: CharacterInput) -> CharacterComputed:
    # normalize mods
    char_ext = {k: 0 for k in ci.invested_characteristics}
    if ci.characteristic_mods:
        char_ext.update({k: int(v) for k, v in ci.characteristic_mods.items()})

    skill_ext = {k: 0 for k in ci.invested_skills}
    if ci.skill_mods:
        skill_ext.update({k: int(v) for k, v in ci.skill_mods.items()})

    # totals & mods
    totals: Dict[str, int] = {}
    cmods: Dict[str, int] = {}
    miles: Dict[str, int] = {}

    for cname, invested in ci.invested_characteristics.items():
        total = characteristic_total(invested, char_ext.get(cname, 0))
        mod = characteristic_mod(total)
        totals[cname] = total
        cmods[cname] = mod
        miles[cname] = milestones(total)

    # skills
    bases: Dict[str, int] = {}
    for sname, sinv in ci.invested_skills.items():
        linked = ci.skill_links.get(sname)
        lmod = cmods.get(linked, 0) if linked else 0
        smod = skill_ext.get(sname, 0)
        bases[sname] = skill_base_value(sinv, lmod, smod, cap_mod_to_invested=True)

    lvl = max(1, min(int(ci.level), 100))
    caps = dict(
        skill_cap=max_skill_cap(lvl),
        characteristic_cap=max_characteristic_cap(lvl),
    )

    # pull specific bases for derived resources
    bv_ath = bases.get("Athletics", 0)
    bv_spi = bases.get("Spirit", 0)
    bv_res = bases.get("Resistance", 0)
    bv_alc = bases.get("Alchemy", 0)

    dr = derived_resources(
        level=lvl,
        mile_BOD=miles.get("BOD", 0),
        mile_WIL=miles.get("WIL", 0),
        mile_MAG=miles.get("MAG", 0),
        mile_PRE=miles.get("PRE", 0),
        mile_DEX=miles.get("DEX", 0),
        mile_REF=miles.get("REF", 0),
        bv_athletics=bv_ath,
        bv_spirit=bv_spi,
        bv_resistance=bv_res,
        bv_alchemy=bv_alc,
        # keep sublimation-related bonuses at 0 for now; wire later:
        bonus_hp_flat=0,
        bonus_en_flat=0,
        bonus_fo_flat=0,
        bonus_mo_flat=0,
    )

    return CharacterComputed(
        level=lvl,
        total_xp_for_level=total_xp_for_level(lvl),
        next_level_xp_cost=xp_to_next_level(lvl),
        characteristic_totals=totals,
        characteristic_mods=cmods,
        milestones=miles,
        skill_base_values=bases,
        caps=caps,
        derived=dr,
    )
