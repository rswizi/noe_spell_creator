from datetime import datetime
from typing import Any, Iterable, Optional

from fastapi import APIRouter, Body, HTTPException, Request

from db_mongo import get_col, next_id_str
from server.src.modules.authentification_helpers import require_auth
from server.src.modules.campaign_chat_helpers import (
    build_chat_doc,
    broadcast_campaign_chat,
    insert_chat_doc,
)

router = APIRouter()

CAMPAIGN_COL = get_col("campaigns")
QUEST_COL = get_col("quests")
PROPOSAL_COL = get_col("quest_proposals")
PROPOSAL_EVENT_COL = get_col("proposal_events")

VALID_QUEST_STATUSES = {
    "pending",
    "active",
    "on_hold",
    "completed",
    "failed",
    "abandoned",
    "hidden",
}
VALID_VISIBILITY = {
    "gm_only",
    "party_visible",
    "character_specific",
    "role_restricted",
}
VALID_QUEST_CATEGORIES = {
    "main",
    "side",
    "personal",
    "faction",
    "secret",
    "time_limited",
    "dynamic",
}
VALID_OBJECTIVE_STATUSES = {
    "not_started",
    "ongoing",
    "succeeded",
    "failed",
}
VALID_OBJECTIVE_TYPES = {
    "mandatory",
    "optional",
    "hidden",
    "branching",
}
VALID_OBJECTIVE_PRIORITIES = {"main", "secondary", "tertiary"}

def _sanitize_choice(value: Any, allowed: set[str], default: str) -> str:
    raw = (str(value or "").strip() or "")
    lowered = raw.lower()
    if lowered in allowed:
        return lowered
    if default:
        return default
    return raw

def _build_note_entry(text: str, author: str) -> dict[str, Any]:
    return {
        "id": f"note_{next_id_str('quest_note', padding=5)}",
        "text": text,
        "author": author,
        "createdAt": _current_ts(),
    }

def _apply_tracking(existing: list[str], username: str, action: str) -> list[str]:
    clean = [entry for entry in (existing or []) if entry]
    normalized = []
    seen = set()
    for entry in clean:
        low = entry.lower()
        if low not in seen:
            seen.add(low)
            normalized.append(entry)
    lower_user = username.lower()
    if action == "track":
        if lower_user not in {name.lower() for name in normalized}:
            normalized.append(username)
    elif action == "untrack":
        normalized = [entry for entry in normalized if entry.lower() != lower_user]
    return normalized


def _require_campaign_access(cid: str, user: str, role: str | None) -> dict[str, Any]:
    doc = CAMPAIGN_COL.find_one({"id": cid})
    if not doc:
        raise HTTPException(status_code=404, detail="Campaign not found")
    normalized_role = (role or "").lower()
    if normalized_role == "admin":
        return doc
    if user != doc.get("owner") and user not in (doc.get("members") or []):
        raise HTTPException(status_code=403, detail="Access denied")
    return doc


def _is_campaign_gm(campaign: dict[str, Any], user: str, role: str | None) -> bool:
    if not campaign:
        return False
    normalized_role = (role or "").lower()
    if normalized_role == "admin":
        return True
    username = user.lower()
    owner = (campaign.get("owner") or "").lower()
    if owner and owner == username:
        return True
    assistants = campaign.get("assistant_gms") or []
    for helper in assistants:
        if not helper:
            continue
        if helper.lower() == username:
            return True
    return False


def _sanitize_docs(docs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized = []
    for doc in docs:
        copy = dict(doc)
        copy.pop("_id", None)
        sanitized.append(copy)
    return sanitized


def _fetch_quest(cid: str, quest_id: str) -> dict[str, Any]:
    quest = QUEST_COL.find_one({"campaignId": cid, "id": quest_id})
    if not quest:
        raise HTTPException(status_code=404, detail="Quest not found")
    return quest


def _current_ts() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _normalize_objectives(raw: Iterable[Any], quest_id: str | None = None) -> list[dict[str, Any]]:
    if not raw:
        return []
    normalized: list[dict[str, Any]] = []
    for idx, entry in enumerate(raw, start=1):
        title = ""
        description = ""
        status = "not_started"
        obj_type = "mandatory"
        priority = "secondary"
        order = idx
        obj_id = ""
        if isinstance(entry, dict):
            title = (entry.get("title") or entry.get("label") or entry.get("name") or "").strip()
            description = (entry.get("description") or "").strip()
            status = _sanitize_choice(entry.get("status") or entry.get("state"), VALID_OBJECTIVE_STATUSES, "not_started")
            obj_type = _sanitize_choice(entry.get("type") or entry.get("objectiveType"), VALID_OBJECTIVE_TYPES, "mandatory")
            priority = _sanitize_choice(entry.get("priority") or entry.get("priorityLevel"), VALID_OBJECTIVE_PRIORITIES, "secondary")
            order = entry.get("order") if isinstance(entry.get("order"), int) else idx
            obj_id = (entry.get("id") or entry.get("objectiveId") or "").strip()
        else:
            title = str(entry or "").strip()
        if not title:
            continue
        if not obj_id:
            if quest_id:
                obj_id = f"{quest_id}-obj-{idx}"
            else:
                obj_id = f"obj_{next_id_str('quest_obj', padding=4)}"
        normalized.append({
            "id": obj_id,
            "title": title,
            "description": description,
            "status": status,
            "state": status,
            "type": obj_type,
            "priority": priority,
            "order": order,
        })
    return normalized


def _normalize_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, Iterable):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _split_quests(
    quests: Iterable[dict[str, Any]], user: str, is_gm: bool
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    group = []
    personal = []
    archive = []
    for quest in quests:
        entry = dict(quest)
        entry.pop("_id", None)
        status = (entry.get("status") or "").lower()
        qtype = (entry.get("type") or "").lower()
        visibility = (entry.get("visibility") or "").lower()
        created_by = (entry.get("createdBy") or "").lower()
        is_owner = created_by and created_by == user.lower()
        if status == "archived":
            if qtype == "personal" and (is_gm or is_owner):
                archive.append(entry)
            elif qtype == "group" and (is_gm or visibility.startswith("group.visible")):
                archive.append(entry)
            continue
        if qtype == "group":
            if not is_gm and not visibility.startswith("group.visible"):
                continue
            group.append(entry)
        elif qtype == "personal":
            if not is_gm and not is_owner:
                continue
            personal.append(entry)
    return group, personal, archive


def _record_proposal_event(
    action: str,
    username: str,
    cid: str,
    proposal_id: str,
    detail: Optional[dict[str, Any]] = None,
) -> None:
    PROPOSAL_EVENT_COL.insert_one(
        {
            "ts": _current_ts(),
            "campaignId": cid,
            "proposalId": proposal_id,
            "action": action,
            "user": username,
            "detail": detail or {},
        }
    )


async def _notify_proposal_action(cid: str, username: str, text: str) -> None:
    doc = build_chat_doc(cid, username, {"text": text, "visibility": "public", "type": "notification"})
    insert_chat_doc(doc)
    await broadcast_campaign_chat(cid, doc)


@router.get("/campaigns/{cid}/quests")
async def list_campaign_quests(req: Request, cid: str):
    user, role = require_auth(req)
    campaign = _require_campaign_access(cid, user, role)
    is_gm = _is_campaign_gm(campaign, user, role)
    raw_quests = list(QUEST_COL.find({"campaignId": cid}))
    group, personal, archive = _split_quests(raw_quests, user, is_gm)
    raw_proposals = PROPOSAL_COL.find({"campaignId": cid})
    proposals = _sanitize_docs(raw_proposals)
    return {
        "status": "success",
        "quests": {
            "group": sorted(group, key=lambda q: q.get("createdAt") or q.get("updatedAt") or "", reverse=True),
            "personal": sorted(personal, key=lambda q: q.get("createdAt") or q.get("updatedAt") or "", reverse=True),
            "archive": sorted(archive, key=lambda q: q.get("createdAt") or q.get("updatedAt") or "", reverse=True),
            "proposals": sorted(proposals, key=lambda p: p.get("createdAt") or "", reverse=True),
        },
    }


@router.post("/campaigns/{cid}/quests")
async def create_campaign_quest(req: Request, cid: str, payload: dict[str, Any] | None = Body(None)):
    user, role = require_auth(req)
    campaign = _require_campaign_access(cid, user, role)
    if not _is_campaign_gm(campaign, user, role):
        raise HTTPException(status_code=403, detail="Only GMs can create quests")
    if not payload:
        raise HTTPException(status_code=400, detail="Missing quest payload")
    title = (payload.get("title") or payload.get("name") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Quest title is required")
    subtitle = (payload.get("subtitle") or payload.get("tagline") or "").strip()
    description = (payload.get("description") or "").strip()
    scope = (payload.get("scope") or payload.get("type") or "group").strip().lower()
    if scope not in {"group", "personal"}:
        scope = "group"
    quest_kind = _sanitize_choice(payload.get("questKind") or payload.get("quest_type") or "main", VALID_QUEST_CATEGORIES, "main")
    status = _sanitize_choice(payload.get("status") or "pending", VALID_QUEST_STATUSES, "pending")
    visibility = _sanitize_choice(payload.get("visibility") or "party_visible", VALID_VISIBILITY, "party_visible")
    priority = _sanitize_choice(payload.get("priority") or "main", VALID_OBJECTIVE_PRIORITIES, "main")
    assigned = _normalize_list(payload.get("assignedTo") or [user])
    tags = _normalize_list(payload.get("tags") or payload.get("labels") or [])
    faction = (payload.get("faction") or "").strip()
    session = (payload.get("session") or "").strip()
    locked = bool(payload.get("locked"))
    tracked_by = _normalize_list(payload.get("trackedBy") or payload.get("tracked_by") or [])
    pinned_by = _normalize_list(payload.get("pinnedBy") or payload.get("pinned_by") or [])
    if payload.get("tracked"):
        if user not in tracked_by:
            tracked_by.append(user)
    if payload.get("pinned"):
        if user not in pinned_by:
            pinned_by.append(user)
    notes_raw = payload.get("notes") or []
    personal_notes = []
    for entry in (notes_raw if isinstance(notes_raw, list) else [notes_raw]):
        text = str(entry) if isinstance(entry, str) else str(entry.get("text") or "")
        text = text.strip()
        if not text:
            continue
        note_author = (entry.get("author") if isinstance(entry, dict) else user) or user
        personal_notes.append(_build_note_entry(text, note_author))
    theories_raw = payload.get("theories") or []
    theories = []
    for entry in (theories_raw if isinstance(theories_raw, list) else [theories_raw]):
        text = str(entry) if isinstance(entry, str) else str(entry.get("text") or "")
        text = text.strip()
        if not text:
            continue
        author = (entry.get("author") if isinstance(entry, dict) else user) or user
        theories.append(_build_note_entry(text, author))
    quest_id = f"quest_{next_id_str('quest', padding=6)}"
    objectives = _normalize_objectives(payload.get("objectives") or [], quest_id)
    now = _current_ts()
    doc = {
        "id": quest_id,
        "campaignId": cid,
        "type": scope,
        "quest_kind": quest_kind,
        "status": status,
        "priority": priority,
        "title": title,
        "subtitle": subtitle,
        "description": description,
        "visibility": visibility,
        "assignedTo": assigned,
        "faction": faction,
        "session": session,
        "locked": locked,
        "tracked_by": tracked_by,
        "pinned_by": pinned_by,
        "personalNotes": personal_notes,
        "theories": theories,
        "tags": tags,
        "objectives": objectives,
        "createdBy": user,
        "createdAt": now,
        "updatedAt": now,
    }
    QUEST_COL.insert_one(doc)
    return {"status": "success", "quest": _sanitize_docs([doc])[0]}


@router.patch("/campaigns/{cid}/quests/{quest_id}")
async def update_campaign_quest(
    req: Request, cid: str, quest_id: str, payload: dict[str, Any] | None = Body(None)
):
    user, role = require_auth(req)
    campaign = _require_campaign_access(cid, user, role)
    if not _is_campaign_gm(campaign, user, role):
        raise HTTPException(status_code=403, detail="Only GMs can edit quests")
    if not payload:
        raise HTTPException(status_code=400, detail="Missing payload")
    quest = _fetch_quest(cid, quest_id)
    updates: dict[str, Any] = {}
    override_fields = {
        "title": payload.get("title"),
        "subtitle": payload.get("subtitle"),
        "description": payload.get("description"),
        "visibility": _sanitize_choice(payload.get("visibility"), VALID_VISIBILITY, quest.get("visibility") or "party_visible"),
        "status": _sanitize_choice(payload.get("status"), VALID_QUEST_STATUSES, quest.get("status") or "pending"),
        "quest_kind": _sanitize_choice(payload.get("questKind") or payload.get("quest_type"), VALID_QUEST_CATEGORIES, quest.get("quest_kind") or "main"),
        "priority": _sanitize_choice(payload.get("priority"), VALID_OBJECTIVE_PRIORITIES, quest.get("priority") or "main"),
        "faction": payload.get("faction"),
        "session": payload.get("session"),
        "locked": payload.get("locked"),
    }
    for key, value in override_fields.items():
        if value is None:
            continue
        updates[key] = value
    if "assignedTo" in payload:
        updates["assignedTo"] = _normalize_list(payload.get("assignedTo") or [])
    if "tags" in payload:
        updates["tags"] = _normalize_list(payload.get("tags") or [])
    if "objectives" in payload:
        updates["objectives"] = _normalize_objectives(payload.get("objectives") or [], quest_id)
    if updates:
        updates["updatedAt"] = _current_ts()
        QUEST_COL.update_one({"campaignId": cid, "id": quest_id}, {"$set": updates})
    updated = QUEST_COL.find_one({"campaignId": cid, "id": quest_id})
    return {"status": "success", "quest": _sanitize_docs([updated])[0]}


@router.delete("/campaigns/{cid}/quests/{quest_id}")
async def delete_campaign_quest(cid: str, quest_id: str, req: Request):
    user, role = require_auth(req)
    campaign = _require_campaign_access(cid, user, role)
    if not _is_campaign_gm(campaign, user, role):
        raise HTTPException(status_code=403, detail="Only GMs can delete quests")
    result = QUEST_COL.delete_one({"campaignId": cid, "id": quest_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Quest not found")
    return {"status": "success"}


@router.patch("/campaigns/{cid}/quests/{quest_id}/objectives/{objective_id}")
async def update_quest_objective(
    req: Request, cid: str, quest_id: str, objective_id: str, payload: dict[str, Any] | None = Body(None)
):
    user, role = require_auth(req)
    campaign = _require_campaign_access(cid, user, role)
    quest = _fetch_quest(cid, quest_id)
    if not payload:
        raise HTTPException(status_code=400, detail="Missing payload")
    gm = _is_campaign_gm(campaign, user, role)
    if not gm:
        visibility = (quest.get("visibility") or "").lower()
        if visibility == "gm_only":
            raise HTTPException(status_code=403, detail="Quest not visible to you")
        username = user.lower()
        assigned = [(c or "").strip().lower() for c in (quest.get("assignedTo") or [])]
        creator = (quest.get("createdBy") or "").lower()
        if username not in assigned and creator != username:
            raise HTTPException(status_code=403, detail="Not allowed to update this objective")
    objective = None
    for entry in (quest.get("objectives") or []):
        if (entry.get("id") or "") == objective_id:
            objective = entry
            break
    if not objective:
        raise HTTPException(status_code=404, detail="Objective not found")
    updated = False
    if "title" in payload and isinstance(payload.get("title"), str):
        children = payload.get("title").strip()
        objective["title"] = children
        updated = True
    if "description" in payload and isinstance(payload.get("description"), str):
        objective["description"] = payload.get("description").strip()
        updated = True
    if "status" in payload:
        new_status = _sanitize_choice(payload.get("status"), VALID_OBJECTIVE_STATUSES, objective.get("status") or "not_started")
        objective["status"] = new_status
        objective["state"] = new_status
        updated = True
    if updated:
        QUEST_COL.update_one({"campaignId": cid, "id": quest_id}, {"$set": {"objectives": quest.get("objectives"), "updatedAt": _current_ts()}})
    return {"status": "success", "quest": _sanitize_docs([quest])[0]}


@router.post("/campaigns/{cid}/quests/{quest_id}/notes")
async def add_quest_note(
    req: Request, cid: str, quest_id: str, payload: dict[str, Any] | None = Body(None)
):
    user, role = require_auth(req)
    _require_campaign_access(cid, user, role)
    quest = _fetch_quest(cid, quest_id)
    text = (payload or {}).get("text") if payload else None
    if not text:
        raise HTTPException(status_code=400, detail="Note text is required")
    try:
        note_text = str(text).strip()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid note text")
    if not note_text:
        raise HTTPException(status_code=400, detail="Note text is required")
    notes = quest.get("personalNotes") or []
    notes.append(_build_note_entry(note_text, user))
    QUEST_COL.update_one({"campaignId": cid, "id": quest_id}, {"$set": {"personalNotes": notes, "updatedAt": _current_ts()}})
    updated = _fetch_quest(cid, quest_id)
    return {"status": "success", "quest": _sanitize_docs([updated])[0]}


@router.post("/campaigns/{cid}/quests/{quest_id}/theories")
async def add_quest_theory(
    req: Request, cid: str, quest_id: str, payload: dict[str, Any] | None = Body(None)
):
    user, role = require_auth(req)
    _require_campaign_access(cid, user, role)
    quest = _fetch_quest(cid, quest_id)
    text = (payload or {}).get("text") if payload else None
    if not text:
        raise HTTPException(status_code=400, detail="Theory text is required")
    theory_text = str(text).strip()
    if not theory_text:
        raise HTTPException(status_code=400, detail="Theory text is required")
    theories = quest.get("theories") or []
    theories.append(_build_note_entry(theory_text, user))
    QUEST_COL.update_one({"campaignId": cid, "id": quest_id}, {"$set": {"theories": theories, "updatedAt": _current_ts()}})
    updated = _fetch_quest(cid, quest_id)
    return {"status": "success", "quest": _sanitize_docs([updated])[0]}


@router.post("/campaigns/{cid}/quests/{quest_id}/tracking")
async def update_quest_tracking(
    req: Request, cid: str, quest_id: str, payload: dict[str, Any] | None = Body(None)
):
    user, role = require_auth(req)
    _require_campaign_access(cid, user, role)
    quest = _fetch_quest(cid, quest_id)
    track_type = (payload or {}).get("type", "").strip().lower()
    action = (payload or {}).get("action", "").strip().lower()
    if track_type not in {"tracked", "pinned"} or action not in {"track", "untrack"}:
        raise HTTPException(status_code=400, detail="Invalid tracking request")
    field = "tracked_by" if track_type == "tracked" else "pinned_by"
    updated_list = _apply_tracking(quest.get(field) or [], user, "track" if action == "track" else "untrack")
    QUEST_COL.update_one({"campaignId": cid, "id": quest_id}, {"$set": {field: updated_list, "updatedAt": _current_ts()}})
    updated = _fetch_quest(cid, quest_id)
    return {"status": "success", "quest": _sanitize_docs([updated])[0]}


@router.post("/campaigns/{cid}/quests/{quest_id}/proposals")
async def create_quest_proposal(
    req: Request, cid: str, quest_id: str, payload: dict[str, Any] | None = Body(None)
):
    user, role = require_auth(req)
    campaign = _require_campaign_access(cid, user, role)
    quest = QUEST_COL.find_one({"campaignId": cid, "id": quest_id})
    if not quest:
        raise HTTPException(status_code=404, detail="Quest not found")
    if (quest.get("type") or "").lower() != "personal":
        raise HTTPException(status_code=400, detail="Only personal quests can be proposed")
    is_gm = _is_campaign_gm(campaign, user, role)
    if not is_gm and (quest.get("createdBy") or "").lower() != user.lower():
        raise HTTPException(status_code=403, detail="Not allowed to propose this quest")
    if payload is None:
        payload = {}
    message = (payload.get("message") or "").strip()
    now = _current_ts()
    proposal_id = f"proposal_{next_id_str('quest_proposal', padding=6)}"
    snapshot = {
        "name": quest.get("name"),
        "description": quest.get("description"),
        "objectives": quest.get("objectives") or [],
        "visibility": quest.get("visibility"),
    }
    doc = {
        "proposalId": proposal_id,
        "sourceQuestId": quest_id,
        "authorId": user,
        "campaignId": cid,
        "status": "open",
        "snapshot": snapshot,
        "notes": message,
        "votes": [],
        "createdAt": now,
        "updatedAt": now,
    }
    PROPOSAL_COL.insert_one(doc)
    return {"status": "success", "proposal": _sanitize_docs([doc])[0]}


@router.post("/campaigns/{cid}/proposals/{proposal_id}/vote")
async def vote_on_proposal(
    req: Request, cid: str, proposal_id: str, payload: dict[str, Any] | None = Body(None)
):
    user, role = require_auth(req)
    _require_campaign_access(cid, user, role)
    if not payload:
        raise HTTPException(status_code=400, detail="Missing vote payload")
    vote_value = (payload.get("vote") or "").strip().lower()
    if vote_value not in {"agree", "disagree"}:
        raise HTTPException(status_code=400, detail="Invalid vote option")
    comment = (payload.get("comment") or "").strip()
    proposal = PROPOSAL_COL.find_one({"campaignId": cid, "proposalId": proposal_id})
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if (proposal.get("status") or "").lower() not in {"open", "changes_requested"}:
        raise HTTPException(status_code=400, detail="Proposal is no longer open for voting")
    now = _current_ts()
    existing_votes = [
        v for v in (proposal.get("votes") or []) if (v.get("userId") or "").lower() != user.lower()
    ]
    vote_entry = {"userId": user, "vote": vote_value, "comment": comment, "votedAt": now}
    updated_votes = existing_votes + [vote_entry]
    PROPOSAL_COL.update_one(
        {"campaignId": cid, "proposalId": proposal_id},
        {"$set": {"votes": updated_votes, "updatedAt": now}},
    )
    updated = PROPOSAL_COL.find_one({"campaignId": cid, "proposalId": proposal_id})
    return {"status": "success", "proposal": _sanitize_docs([updated])[0]}


@router.post("/campaigns/{cid}/proposals/{proposal_id}/review")
async def review_proposal(
    req: Request, cid: str, proposal_id: str, payload: dict[str, Any] | None = Body(None)
):
    user, role = require_auth(req)
    campaign = _require_campaign_access(cid, user, role)
    if not _is_campaign_gm(campaign, user, role):
        raise HTTPException(status_code=403, detail="Only the GM can review proposals")
    if not payload:
        raise HTTPException(status_code=400, detail="Missing review payload")
    action = (payload.get("action") or "").strip().lower()
    if action not in {"approve", "reject", "request_changes"}:
        raise HTTPException(status_code=400, detail="Invalid review action")
    proposal = PROPOSAL_COL.find_one({"campaignId": cid, "proposalId": proposal_id})
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    status_map = {
        "approve": "approved",
        "reject": "rejected",
        "request_changes": "changes_requested",
    }
    current_status = (proposal.get("status") or "").lower()
    if current_status not in {"open", "changes_requested"}:
        raise HTTPException(status_code=400, detail="Proposal already closed")
    now = _current_ts()
    review_entry = {
        "action": action,
        "by": user,
        "message": (payload.get("message") or "").strip(),
        "at": now,
    }
    update_fields = {
        "status": status_map[action],
        "review": review_entry,
        "updatedAt": now,
    }
    group_quest_doc = None
    if action == "approve":
        snapshot = proposal.get("snapshot") or {}
        group_quest_id = f"quest_{next_id_str('quest', padding=6)}"
        objectives = _normalize_objectives(snapshot.get("objectives") or [])
        visibility = (snapshot.get("visibility") or "group.visible").strip().lower()
        if not visibility.startswith("group"):
            visibility = "group.visible"
        tags = _normalize_list(snapshot.get("tags") or [])
        group_doc = {
            "id": group_quest_id,
            "campaignId": cid,
            "type": "group",
            "status": "pending",
            "name": snapshot.get("name") or "Group Quest",
            "description": snapshot.get("description") or "",
            "objectives": objectives,
            "createdBy": user,
            "assignedTo": snapshot.get("assignedTo") or ["party"],
            "visibility": visibility,
            "tags": tags,
            "sourceProposalId": proposal_id,
            "createdAt": now,
            "updatedAt": now,
        }
        QUEST_COL.insert_one(group_doc)
        update_fields["groupQuestId"] = group_quest_id
        group_quest_doc = group_doc
        source_quest_id = proposal.get("sourceQuestId")
        if source_quest_id:
            QUEST_COL.update_one(
                {"campaignId": cid, "id": source_quest_id},
                {"$set": {"status": "archived", "updatedAt": now}},
            )
    PROPOSAL_COL.update_one(
        {"campaignId": cid, "proposalId": proposal_id}, {"$set": update_fields}
    )
    updated = PROPOSAL_COL.find_one({"campaignId": cid, "proposalId": proposal_id})
    response = {"status": "success", "proposal": _sanitize_docs([updated])[0]}
    if group_quest_doc:
        response["groupQuest"] = _sanitize_docs([group_quest_doc])[0]
    return response
