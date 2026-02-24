import os
from dataclasses import dataclass
from functools import lru_cache


WIKI_ROLES = ("viewer", "editor", "admin")


def _truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    raw = str(value).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _csv_roles(raw: str | None, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if raw is None:
        return fallback
    parsed = tuple(
        role
        for role in [str(part).strip().lower() for part in str(raw).split(",")]
        if role
    )
    if not parsed:
        return fallback
    return parsed


@dataclass(frozen=True)
class WikiSettings:
    enabled: bool
    require_auth: bool
    strict_startup: bool
    max_doc_bytes: int
    default_view_roles: tuple[str, ...]
    default_edit_roles: tuple[str, ...]


@lru_cache
def get_wiki_settings() -> WikiSettings:
    max_doc_bytes_raw = str(os.getenv("WIKI_MAX_DOC_BYTES") or "200000").strip()
    try:
        max_doc_bytes = max(1000, int(max_doc_bytes_raw))
    except Exception:
        max_doc_bytes = 200000
    return WikiSettings(
        enabled=_truthy(os.getenv("WIKI_ENABLED"), default=True),
        require_auth=_truthy(os.getenv("WIKI_REQUIRE_AUTH"), default=True),
        strict_startup=_truthy(os.getenv("WIKI_STRICT_STARTUP"), default=False),
        max_doc_bytes=max_doc_bytes,
        default_view_roles=_csv_roles(os.getenv("WIKI_DEFAULT_VIEW_ROLES"), ("viewer", "editor", "admin")),
        default_edit_roles=_csv_roles(os.getenv("WIKI_DEFAULT_EDIT_ROLES"), ("editor", "admin")),
    )


@dataclass(frozen=True)
class WikiEnvValidation:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]


def validate_wiki_environment() -> WikiEnvValidation:
    cfg = get_wiki_settings()
    if not cfg.enabled:
        return WikiEnvValidation(errors=(), warnings=("WIKI_ENABLED is false; wiki routes remain mounted but are expected to be blocked by policy.",))
    errors: list[str] = []
    warnings: list[str] = []
    for role in cfg.default_view_roles + cfg.default_edit_roles:
        if role not in WIKI_ROLES:
            errors.append(f"Unsupported wiki role in defaults: {role}")
    if not cfg.default_view_roles:
        errors.append("WIKI_DEFAULT_VIEW_ROLES cannot be empty.")
    if not cfg.default_edit_roles:
        errors.append("WIKI_DEFAULT_EDIT_ROLES cannot be empty.")
    if not os.getenv("MONGODB_URI"):
        warnings.append("MONGODB_URI is not set via environment. Application may rely on .env fallback.")

    r2_enabled = _truthy(os.getenv("R2_ENABLED"), default=False)
    if r2_enabled:
        required = {
            "R2_BUCKET": os.getenv("R2_BUCKET") or os.getenv("R2_BUCKET_NAME"),
            "R2_ENDPOINT": os.getenv("R2_ENDPOINT"),
            "R2_ACCESS_KEY_ID": os.getenv("R2_ACCESS_KEY_ID"),
            "R2_SECRET_ACCESS_KEY": os.getenv("R2_SECRET_ACCESS_KEY"),
        }
        missing = [name for name, value in required.items() if not str(value or "").strip()]
        if missing:
            errors.append(f"R2 is enabled but missing required vars: {', '.join(missing)}")
        if not str(os.getenv("R2_PUBLIC_BASE_URL") or os.getenv("R2_PUBLIC_URL") or os.getenv("R2_CUSTOM_DOMAIN") or "").strip():
            warnings.append("R2 enabled without public base URL/domain; asset fetches may proxy through API.")
    return WikiEnvValidation(errors=tuple(errors), warnings=tuple(warnings))

