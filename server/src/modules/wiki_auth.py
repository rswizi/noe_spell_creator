from __future__ import annotations

from fastapi import HTTPException, Request

from server.src.modules.authentification_helpers import (
    find_user,
    get_auth_token,
    get_session_identity,
)
from server.src.modules.wiki_config import get_wiki_settings
from server.src.modules.wiki_service import (
    normalize_wiki_role,
    resolve_wiki_role,
    role_at_least,
)


def _resolve_wiki_identity(request: Request) -> dict[str, str | bool]:
    cfg = get_wiki_settings()
    if not cfg.enabled:
        raise HTTPException(status_code=503, detail="Wiki is disabled")

    token = get_auth_token(request) or ""
    identity = get_session_identity(token)
    if not identity:
        if cfg.require_auth:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return {
            "username": "anonymous",
            "role": "user",
            "wiki_role": "viewer",
            "is_anonymous": True,
        }

    username, _base_role, effective_role = identity
    user_doc = find_user(username) or {}
    wiki_role = normalize_wiki_role(resolve_wiki_role(effective_role, user_doc))
    return {
        "username": username,
        "role": effective_role,
        "wiki_role": wiki_role,
        "is_anonymous": False,
    }


def _require_wiki_role(request: Request, minimum: str) -> dict[str, str | bool]:
    auth = _resolve_wiki_identity(request)
    if not role_at_least(str(auth.get("wiki_role") or "viewer"), minimum):
        raise HTTPException(status_code=403, detail="Forbidden")
    return auth


def require_wiki_viewer(request: Request):
    return _require_wiki_role(request, "viewer")


def require_wiki_editor(request: Request):
    return _require_wiki_role(request, "editor")


def require_wiki_admin(request: Request):
    return _require_wiki_role(request, "admin")
