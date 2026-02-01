import os
import secrets

from fastapi import HTTPException, Request

from server.src.modules.authentification_helpers import get_auth_token, require_auth

API_TOKEN = os.environ.get("API_TOKEN", "")
ENV = os.environ.get("ENV", "development").lower()

if not API_TOKEN:
    print(
        "NOTICE: No API_TOKEN configured for wiki APIs; session-based logins will be used instead."
        + (" (Production workload should ensure admins are authenticated)." if ENV == "production" else "")
    )


def require_wiki_admin(request: Request):
    try:
        username, role = require_auth(request, roles=["admin", "moderator"])
        return {"username": username, "role": role}
    except HTTPException as exc:
        token = get_auth_token(request)
        if token and API_TOKEN and secrets.compare_digest(token, API_TOKEN):
            return {"username": "api", "role": "api"}
        raise exc
