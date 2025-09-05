from typing import Optional
import re
from db_mongo import get_col

APO_STAGE_BASE = {
    "Immature Stage": 5,
    "Stage I": 7,
    "Stage II": 10,
    "Stage III": 14,
    "Stage IV": 19,
    "Stage V": 25,
}
APO_TYPES = {"Terrain", "Ephemeral", "Personal"}

APO_TYPE_BONUS = {
    "Terrain":   {"power": 2, "stability": 0, "amplitude": 0},
    "Ephemeral": {"power": 0, "stability": 0, "amplitude": 2},
    "Personal":  {"power": 0, "stability": 2, "amplitude": 0},
}

P2S_COST = 5
P2S_GAIN = 2
P2A_COST = 2
S2A_COST = 2

_ROMAN = {
    "i":1,"ii":2,"iii":3,"iv":4,"v":5,"vi":6,"vii":7,"viii":8,"ix":9,"x":10,
    "xi":11,"xii":12,"xiii":13,"xiv":14,"xv":15
}

def _can_edit_apotheosis(doc, username, role):
    return bool(doc) and (doc.get("creator") == username or role in ("moderator", "admin"))

def _stage_index_from_string(s: str) -> Optional[int]:
    """Extract a stage index (1-based) from things like 'Stage II', 'stage 2', 'II', '2'."""
    if not s:
        return None
    t = s.strip().lower()

    m = re.search(r"\d+", t)
    if m:
        try:
            return int(m.group(0))
        except Exception:
            pass

    m = re.search(r"\b([ivxlcdm]+)\b", t)
    if m:
        return _ROMAN.get(m.group(1), None)
    return None

def apo_stage_stability(stage: str) -> int:
    """
    Resolve base stability from APO_STAGE_BASE using a tolerant stage parser.
    Falls back to 0 if no match.
    """
    if not isinstance(APO_STAGE_BASE, dict):
        return 0

    s = (stage or "").strip().lower()
    for k, v in APO_STAGE_BASE.items():
        if str(k).strip().lower() == s:
            return int(v or 0)

    want = _stage_index_from_string(stage)
    if want is not None:
        for k, v in APO_STAGE_BASE.items():
            if _stage_index_from_string(str(k)) == want:
                return int(v or 0)

    return 0

def apo_type_bonus(apo_type: str) -> dict:
    """
    Return a dict with keys power/stability/amplitude from APO_TYPE_BONUS.
    Case-insensitive; defaults to zeros if not found.
    """
    t = (apo_type or "").strip().lower()
    if isinstance(APO_TYPE_BONUS, dict):
        for k, v in APO_TYPE_BONUS.items():
            if str(k).strip().lower() == t:
                # normalize shape
                return {
                    "power": int(v.get("power", 0)) if isinstance(v, dict) else 0,
                    "stability": int(v.get("stability", 0)) if isinstance(v, dict) else 0,
                    "amplitude": int(v.get("amplitude", 0)) if isinstance(v, dict) else 0,
                }
    return {"power": 0, "stability": 0, "amplitude": 0}

def tier_from_total_difficulty(total: int) -> str:
    """
    Simple tiering: every 5 difficulty raises the tier by 1.
    Tweak the divisor to match your doc if needed.
    """
    try:
        n = int(total or 0)
    except Exception:
        n = 0
    tier_num = 1 + (n // 5)
    return f"Tier {tier_num}"

def compute_apotheosis_stats(
    characteristic_value: int,
    stage: str,
    apo_type: str,
    constraint_ids: list[str],
    trade_p2s_steps: int = 0,
    trade_p2a_steps: int = 0,
    trade_s2a_steps: int = 0,
) -> dict:

    col = get_col("apotheosis_constraints")
    docs = list(col.find({"id": {"$in": [str(x) for x in (constraint_ids or [])]}}))

    total_difficulty = sum(int(d.get("difficulty", 0)) for d in docs)

    stability = apo_stage_stability(stage)
    power     = int(characteristic_value or 0) + total_difficulty
    amplitude = 0

    tbonus = apo_type_bonus(apo_type)
    power     += tbonus.get("power", 0)
    stability += tbonus.get("stability", 0)
    amplitude += tbonus.get("amplitude", 0)

    forbid_p2s = False
    for d in docs:
        stability += int(d.get("stability_delta", 0))
        amplitude += int(d.get("amplitude_bonus", 0))
        if bool(d.get("forbid_p2s", False)):
            forbid_p2s = True

    p2s_applied = 0
    if not forbid_p2s and trade_p2s_steps > 0:
        for _ in range(int(trade_p2s_steps)):
            if power >= P2S_COST:
                power -= P2S_COST
                stability += P2S_GAIN
                p2s_applied += 1
            else:
                break

    p2a_applied = 0
    if trade_p2a_steps > 0:
        for _ in range(int(trade_p2a_steps)):
            if power >= P2A_COST:
                power -= P2A_COST
                amplitude += 1
                p2a_applied += 1
            else:
                break

    s2a_applied = 0
    if trade_s2a_steps > 0:
        for _ in range(int(trade_s2a_steps)):
            if stability >= S2A_COST:
                stability -= S2A_COST
                amplitude += 1
                s2a_applied += 1
            else:
                break

    diameter = 17 + 2 * max(0, int(amplitude))

    return {
        "stability": max(0, int(stability)),
        "power": max(0, int(power)),
        "amplitude": max(0, int(amplitude)),
        "diameter": int(diameter),
        "total_difficulty": int(total_difficulty),
        "tier": tier_from_total_difficulty(total_difficulty),
        "flags": {"forbid_p2s": forbid_p2s, "p2s_applied": p2s_applied, "p2a_applied": p2a_applied, "s2a_applied": s2a_applied}
    }
