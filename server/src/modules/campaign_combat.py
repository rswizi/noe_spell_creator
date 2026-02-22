import datetime
from typing import Any

from pymongo import ReturnDocument

from db_mongo import get_col, next_id_str

COMBAT_COLL = "campaign_combats"


def combat_collection():
    return get_col(COMBAT_COLL)


def _current_ts():
    return datetime.datetime.utcnow().isoformat() + "Z"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _sorted_participant_ids(participants: list[dict[str, Any]]) -> list[str]:
    sorted_parts = sorted(
        participants or [],
        key=lambda part: (
            -_safe_int(part.get("initiative")),
            _safe_int(part.get("added_idx")),
            str(part.get("id") or ""),
        ),
    )
    return [part.get("id") for part in sorted_parts if part.get("id")]


def _current_participant_id(doc: dict[str, Any]) -> str:
    order = doc.get("initiative_order") or []
    idx = _safe_int(doc.get("turn_index"))
    if idx < 0 or idx >= len(order):
        return ""
    return str(order[idx] or "")


def _normalized_turn_index(order: list[str], current_pid: str, fallback_index: int = 0) -> int:
    if not order:
        return 0
    if current_pid and current_pid in order:
        return order.index(current_pid)
    idx = max(0, min(_safe_int(fallback_index), len(order) - 1))
    return idx


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
    order = _sorted_participant_ids(participants)
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


def rebuild_initiative_order(
    campaign_id: str,
    combat_id: str,
    keep_current: bool = True,
    bump_turn_token: bool = False,
) -> dict[str, Any] | None:
    coll = combat_collection()
    doc = coll.find_one({"id": combat_id, "campaign_id": campaign_id})
    if not doc:
        return None
    participants = doc.get("participants") or []
    order = _sorted_participant_ids(participants)
    current_pid = _current_participant_id(doc) if keep_current else ""
    turn_index = _normalized_turn_index(order, current_pid, doc.get("turn_index") or 0)
    update: dict[str, Any] = {
        "initiative_order": order,
        "turn_index": turn_index,
    }
    if bump_turn_token and (doc.get("status") == "active"):
        update["turn_token"] = _safe_int(doc.get("turn_token")) + 1
    updated = coll.find_one_and_update(
        {"id": combat_id, "campaign_id": campaign_id},
        {"$set": update},
        return_document=ReturnDocument.AFTER,
    )
    if updated and updated.get("status") == "active":
        process_turn_atomic(updated)
    return updated


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


def end_combat(campaign_id: str, combat_id: str) -> dict[str, Any] | None:
    coll = combat_collection()
    return coll.find_one_and_update(
        {"id": combat_id, "campaign_id": campaign_id},
        {
            "$set": {
                "status": "ended",
                "ended_at": _current_ts(),
            }
        },
        return_document=ReturnDocument.AFTER,
    )


def update_combat_participant(
    campaign_id: str,
    combat_id: str,
    participant_id: str,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    coll = combat_collection()
    doc = coll.find_one({"id": combat_id, "campaign_id": campaign_id})
    if not doc:
        return None
    participants = [dict(part) for part in (doc.get("participants") or [])]
    changed = False
    initiative_changed = False
    for part in participants:
        if str(part.get("id") or "") != participant_id:
            continue
        if "name" in payload:
            part["name"] = str(payload.get("name") or "").strip() or part.get("name") or "Combatant"
            changed = True
        if "initiative" in payload:
            part["initiative"] = _safe_int(payload.get("initiative"))
            changed = True
            initiative_changed = True
        if "notes" in payload or "note" in payload:
            part["notes"] = str(payload.get("notes") or payload.get("note") or "").strip()
            changed = True
        break
    if not changed:
        return doc
    updated = coll.find_one_and_update(
        {"id": combat_id, "campaign_id": campaign_id},
        {"$set": {"participants": participants}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        return None
    return rebuild_initiative_order(
        campaign_id,
        combat_id,
        keep_current=True,
        bump_turn_token=initiative_changed,
    ) or updated


def remove_combat_participant(
    campaign_id: str,
    combat_id: str,
    participant_id: str,
) -> dict[str, Any] | None:
    coll = combat_collection()
    doc = coll.find_one({"id": combat_id, "campaign_id": campaign_id})
    if not doc:
        return None
    participants = [dict(part) for part in (doc.get("participants") or [])]
    filtered = [part for part in participants if str(part.get("id") or "") != participant_id]
    if len(filtered) == len(participants):
        return doc
    updated = coll.find_one_and_update(
        {"id": combat_id, "campaign_id": campaign_id},
        {"$set": {"participants": filtered}},
        return_document=ReturnDocument.AFTER,
    )
    if not updated:
        return None
    return rebuild_initiative_order(
        campaign_id,
        combat_id,
        keep_current=True,
        bump_turn_token=doc.get("status") == "active",
    ) or updated


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
