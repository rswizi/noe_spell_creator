import hashlib
import secrets
from typing import Dict, Optional, Tuple
from fastapi import Request, HTTPException

from db_mongo import get_col

SESSIONS: Dict[str, Tuple[str, str]] = {}
SESSION_ROLE_OVERRIDES: Dict[str, str] = {}
AUTH_TOKEN_COOKIE = "auth_token"

def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def make_token() -> str:
    return secrets.token_hex(16)

def get_auth_token(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    cookie_token = request.cookies.get(AUTH_TOKEN_COOKIE)
    if cookie_token:
        return cookie_token
    return None

def verify_password(input_pw: str, user_doc: dict) -> bool:
    # accept plaintext ('password') or sha256 hash ('password_hash')
    return (
        user_doc.get("password") == input_pw
        or user_doc.get("password_hash") == _sha256(input_pw)
    )

def normalize_email(email: str) -> str:
    return (email or "").strip().lower()

_ALLOWED_ROLES = {"user", "moderator", "admin"}


def _normalize_role(value: str | None) -> str:
    raw = (value or "").strip().lower()
    return raw if raw in _ALLOWED_ROLES else "user"


def get_session_identity(token: str) -> Optional[Tuple[str, str, str]]:
    """Return (username, base_role, effective_role) for a session token."""
    if not token or token not in SESSIONS:
        return None
    username, stored_role = SESSIONS[token]
    base_role = _normalize_role(stored_role)
    override_raw = SESSION_ROLE_OVERRIDES.get(token)
    override_role = _normalize_role(override_raw) if override_raw is not None else ""
    if base_role != "admin":
        SESSION_ROLE_OVERRIDES.pop(token, None)
        return username, base_role, base_role
    effective_role = override_role if override_role == "user" else base_role
    return username, base_role, effective_role


def clear_session(token: str) -> None:
    SESSIONS.pop(token, None)
    SESSION_ROLE_OVERRIDES.pop(token, None)


def set_session_admin_privileges(token: str, enabled: bool) -> Tuple[str, str, str]:
    identity = get_session_identity(token)
    if not identity:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username, base_role, _ = identity
    if base_role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can toggle admin privileges")
    if enabled:
        SESSION_ROLE_OVERRIDES.pop(token, None)
    else:
        SESSION_ROLE_OVERRIDES[token] = "user"
    updated = get_session_identity(token)
    if not updated:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return updated

def find_user(username: str) -> Optional[dict]:
    # always exclude _id when returning data to the app
    return get_col("users").find_one({"username": username}, {"_id": 0})

def require_auth(request: Request, roles: Optional[list[str]] = None) -> Tuple[str, str]:
    """Return (username, role) or raise Exception."""
    token = get_auth_token(request)
    identity = get_session_identity(token or "")
    if not identity:
        raise HTTPException(status_code=401, detail="Not authenticated")
    username, _base_role, role = identity
    if roles and role not in roles:
        raise HTTPException(status_code=403, detail="Forbidden")
    return username, role
