from typing import Iterable, Tuple

CATEGORY_BY_MAX_MP: Iterable[Tuple[str, int]] = [
    ("Novice", 12),
    ("Apprentice", 17),
    ("Disciple", 22),
    ("Adept", 27),
    ("Mage", 32),
    ("Magister", 37),
    ("High Mage", 42),
    ("Master", 52),
    ("Grand Master", 62),
    ("Archmage", 75),
    ("Supreme Archmage", 85),
]
DEFAULT_CATEGORY = "Avant-garde"

def category_for_mp(mp_cost: int | float | str) -> str:
    """Return the category name for a given MP cost."""
    try:
        mp = int(mp_cost)
    except (TypeError, ValueError):
        return DEFAULT_CATEGORY

    for name, max_mp in CATEGORY_BY_MAX_MP:
        if mp <= max_mp:
            return name
    return DEFAULT_CATEGORY