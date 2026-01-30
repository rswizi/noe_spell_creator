import os
import secrets

from fastapi import HTTPException, Request

from server.src.modules.authentification_helpers import get_auth_token, require_auth

API_TOKEN = os.environ.get("API_TOKEN", "")
ENV = os.environ.get("ENV", "development").lower()

if ENV == "production" and not API_TOKEN:
    raise RuntimeError("API_TOKEN must be set in production for wiki APIs")
elif not API_TOKEN:
    print("WARNING: Running wiki APIs without API_TOKEN (allowed only in non-production environments)")


def require_wiki_admin(request: Request):
    try:
        username, role = require_auth(request, roles=["admin", "moderator"])
        return {"username": username, "role": role}
    except HTTPException as exc:
        token = get_auth_token(request)
        if token and API_TOKEN and secrets.compare_digest(token, API_TOKEN):
            return {"username": "api", "role": "api"}
        raise exc
