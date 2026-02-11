import datetime
import json
import secrets
from typing import Any, Dict, Iterable, Set

from fastapi import WebSocket
from pymongo.errors import DuplicateKeyError

from db_mongo import get_col, next_id_str

CAMPAIGN_CHAT_COL = get_col("campaign_chat")
CAMPAIGN_CHAT_WS: Dict[str, Set[WebSocket]] = {}


def _chat_visibility(val: Any) -> str:
    raw = (str(val) if val is not None else "").strip().lower()
    return raw if raw in {"public", "self", "whisper"} else "public"


def _chat_type(val: Any) -> str:
    raw = (str(val) if val is not None else "").strip().lower()
    return raw if raw in {"message", "roll", "notification"} else "message"


def _chat_lines(val: Any) -> list[str]:
    if isinstance(val, str):
        return [val]
    if isinstance(val, Iterable):
        return [str(line).strip() for line in val if str(line).strip()]
    return []


def _next_chat_id() -> str:
    try:
        return f"msg_{next_id_str('campaign_chat', padding=6)}"
    except Exception:
        return f"msg_{secrets.token_hex(4)}"


def build_chat_doc(cid: str, user: str, body: dict[str, Any]) -> dict:
    ts = body.get("ts")
    try:
        ts_val = int(ts)
    except Exception:
        ts_val = int(datetime.datetime.utcnow().timestamp() * 1000)
    doc = {
        "id": _next_chat_id(),
        "campaign_id": cid,
        "ts": ts_val,
        "visibility": _chat_visibility(body.get("visibility")),
        "type": _chat_type(body.get("type")),
        "text": str(body.get("text") or "").strip()[:800],
        "lines": _chat_lines(body.get("lines")),
        "user": user,
        "character_id": str(body.get("character_id") or "").strip(),
        "character_name": str(body.get("character_name") or "").strip(),
        "character_avatar": str(body.get("character_avatar") or "").strip(),
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    return doc


async def broadcast_campaign_chat(cid: str, msg: dict) -> None:
    if "_id" in msg:
        msg = {k: v for k, v in msg.items() if k != "_id"}
    sockets = list(CAMPAIGN_CHAT_WS.get(cid, set()))
    if not sockets:
        return
    payload = {"type": "chat", "message": msg}
    dead: list[WebSocket] = []
    for ws in sockets:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        CAMPAIGN_CHAT_WS.get(cid, set()).discard(ws)
    if not CAMPAIGN_CHAT_WS.get(cid):
        CAMPAIGN_CHAT_WS.pop(cid, None)


def insert_chat_doc(doc: dict[str, Any]) -> dict[str, Any]:
    try:
        CAMPAIGN_CHAT_COL.insert_one(doc)
    except DuplicateKeyError:
        doc["id"] = f"msg_{secrets.token_hex(4)}"
        CAMPAIGN_CHAT_COL.insert_one(doc)
    return doc
