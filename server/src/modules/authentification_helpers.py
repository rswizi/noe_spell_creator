import hashlib
import secrets
from typing import Optional, Tuple
from fastapi import Request

from db_mongo import get_col, SESSIONS


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def make_token() -> str:
    return secrets.token_hex(16)

def get_auth_token(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
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

def find_user(username: str) -> Optional[dict]:
    # always exclude _id when returning data to the app
    return get_col("users").find_one({"username": username}, {"_id": 0})

def require_auth(request: Request, roles: Optional[list[str]] = None) -> Tuple[str, str]:
    """Return (username, role) or raise Exception."""
    token = get_auth_token(request)
    if not token or token not in SESSIONS:
        raise Exception("Not authenticated")
    username, role = SESSIONS[token]
    if roles and role not in roles:
        raise Exception("Forbidden")
    return username, role