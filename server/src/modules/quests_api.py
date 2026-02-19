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


def _current_ts() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _normalize_objectives(raw: Iterable[Any]) -> list[dict[str, Any]]:
    if not raw:
        return []
    normalized: list[dict[str, Any]] = []
    for idx, entry in enumerate(raw, start=1):
        label = ""
        state = "todo"
        order = idx
        if isinstance(entry, dict):
            label = (entry.get("label") or entry.get("name") or "").strip()
            state = (entry.get("state") or "todo").strip().lower()
            order = entry.get("order") if isinstance(entry.get("order"), int) else idx
        else:
            label = str(entry or "").strip()
        if not label:
            continue
        normalized.append({"label": label, "state": state or "todo", "order": order})
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
async def create_personal_quest(req: Request, cid: str, payload: dict[str, Any] | None = Body(None)):
    user, role = require_auth(req)
    _require_campaign_access(cid, user, role)
    if not payload:
        raise HTTPException(status_code=400, detail="Missing quest payload")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Quest name is required")
    description = (payload.get("description") or "").strip()
    objectives = _normalize_objectives(payload.get("objectives") or [])
    tags = _normalize_list(payload.get("tags") or [])
    assigned = _normalize_list(payload.get("assignedTo") or [user])
    visibility = (payload.get("visibility") or "personal.private").strip().lower()
    if not visibility.startswith("personal"):
        visibility = "personal.private"
    quest_id = f"quest_{next_id_str('quest', padding=6)}"
    now = _current_ts()
    doc = {
        "id": quest_id,
        "campaignId": cid,
        "type": "personal",
        "status": "pending",
        "name": name,
        "description": description,
        "objectives": objectives,
        "createdBy": user,
        "assignedTo": assigned,
        "visibility": visibility,
        "tags": tags,
        "createdAt": now,
        "updatedAt": now,
    }
    QUEST_COL.insert_one(doc)
    return {"status": "success", "quest": _sanitize_docs([doc])[0]}


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
