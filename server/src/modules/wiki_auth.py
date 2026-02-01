from fastapi import Request

from server.src.modules.authentification_helpers import require_auth


def require_wiki_admin(request: Request):
    username, role = require_auth(request, roles=["admin", "moderator"])
    return {"username": username, "role": role}
