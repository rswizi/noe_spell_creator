import datetime
from typing import Any

from pymongo import ReturnDocument

from db_mongo import get_col, next_id_str

COMBAT_COLL = "campaign_combats"


def combat_collection():
    return get_col(COMBAT_COLL)


def _current_ts():
    return datetime.datetime.utcnow().isoformat() + "Z"


def create_combat_doc(
    campaign_id: str,
    gm: str,
    participants: list[dict[str, Any]],
    title: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    comb_id = f"combat_{next_id_str('combat', padding=4)}"
    display_title = (title or "").strip() or comb_id
    display_note = (note or "").strip()
    doc = {
        "id": comb_id,
        "campaign_id": campaign_id,
        "gm": gm,
        "title": display_title,
        "notes": display_note,
        "status": "draft",
        "participants": participants,
        "initiative_order": [],
        "turn_index": 0,
        "round": 1,
        "turn_token": 0,
        "condition_markers": {},
        "joined_users": [],
        "created_at": _current_ts(),
        "started_at": None,
        "ended_at": None,
    }
    combat_collection().insert_one(doc)
    return doc


def get_combat(campaign_id: str, combat_id: str, active_only: bool = False) -> dict[str, Any] | None:
    query = {"id": combat_id, "campaign_id": campaign_id}
    if active_only:
        query["status"] = "active"
    return combat_collection().find_one(query)


def get_active_combat(campaign_id: str) -> dict[str, Any] | None:
    return combat_collection().find_one({"campaign_id": campaign_id, "status": "active"})


def start_combat(campaign_id: str, combat_id: str) -> dict[str, Any]:
    coll = combat_collection()
    doc = coll.find_one({"id": combat_id, "campaign_id": campaign_id})
    if not doc:
        return {}
    participants = doc.get("participants") or []
    if not participants:
        return doc
    sorted_parts = sorted(
        participants,
        key=lambda part: (
            -int(part.get("initiative") or 0),
            int(part.get("added_idx", 0)),
        ),
    )
    order = [part["id"] for part in sorted_parts if part.get("id")]
    update = {
        "status": "active",
        "initiative_order": order,
        "turn_index": 0,
        "round": 1,
        "turn_token": 1,
        "started_at": _current_ts(),
    }
    updated = coll.find_one_and_update(
        {"id": combat_id, "campaign_id": campaign_id},
        {"$set": update},
        return_document=ReturnDocument.AFTER,
    )
    if updated:
        process_turn_atomic(updated)
    return updated or {}


def advance_combat_turn(campaign_id: str, combat_id: str, direction: str = "next") -> dict[str, Any] | None:
    coll = combat_collection()
    doc = coll.find_one({"id": combat_id, "campaign_id": campaign_id, "status": "active"})
    if not doc:
        return None
    order = doc.get("initiative_order") or []

    if not order:
        return doc

    current_index = int(doc.get("turn_index") or 0)
    round_num = int(doc.get("round") or 1)
    token = int(doc.get("turn_token") or 0)
    length = len(order)
    if direction == "prev":
        new_index = (current_index - 1 + length) % length
        if current_index == 0 and round_num > 1:
            round_num = max(1, round_num - 1)
    else:
        new_index = (current_index + 1) % length
        if new_index == 0:
            round_num += 1

    token += 1
    updated = coll.find_one_and_update(
        {"id": combat_id, "campaign_id": campaign_id},
        {
            "$set": {
                "turn_index": new_index,
                "round": round_num,
                "turn_token": token,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated:
        process_turn_atomic(updated)
    return updated


def join_combat(campaign_id: str, combat_id: str, username: str) -> dict[str, Any] | None:
    coll = combat_collection()
    coll.update_one(
        {"id": combat_id, "campaign_id": campaign_id},
        {"$addToSet": {"joined_users": username}},
    )
    return coll.find_one({"id": combat_id, "campaign_id": campaign_id})


def process_turn_atomic(doc: dict[str, Any]) -> None:
    if not doc or doc.get("status") != "active":
        return
    order = doc.get("initiative_order") or []
    if not order:
        return
    idx = int(doc.get("turn_index") or 0)
    if idx < 0 or idx >= len(order):
        return
    pid = order[idx]
    token = int(doc.get("turn_token") or 0)
    markers = doc.get("condition_markers") or {}
    last = int(markers.get(pid) or 0)
    if last >= token:
        return
    combat_collection().update_one(
        {"id": doc["id"], "campaign_id": doc["campaign_id"]},
        {"$set": {f"condition_markers.{pid}": token}},
    )
    apply_condition_effects(doc, pid, token)


def apply_condition_effects(combat_doc: dict[str, Any], participant_id: str, turn_token: int) -> None:
    participants = combat_doc.get("participants") or []
    participant = next((p for p in participants if p.get("id") == participant_id), None)
    if not participant:
        return
    char_id = participant.get("character_id")
    if not char_id:
        return
    char_coll = get_col("characters")
    char_coll.update_one(
        {"id": char_id},
        {
            "$set": {
                "condition_last_round": int(combat_doc.get("round") or 1),
                "condition_last_token": turn_token,
                "condition_processed_at": _current_ts(),
            }
        },
    )
