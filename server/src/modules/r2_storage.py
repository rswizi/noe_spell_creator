import mimetypes
import os
from io import BytesIO
from typing import Any
from urllib.parse import quote

try:
    import boto3
except Exception:  # pragma: no cover
    boto3 = None


def _truthy(value: str | None) -> bool:
    raw = str(value or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _clean_prefix(value: str | None, fallback: str) -> str:
    raw = str(value or fallback).strip().strip("/")
    return raw or fallback


def _safe_segment(value: str) -> str:
    return quote(str(value or "").strip(), safe="-._~")


def _normalize_public_base(value: str | None) -> str:
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return f"https://{raw}"


def _extension_from_content_type(content_type: str | None, fallback_name: str = "") -> str:
    ctype = str(content_type or "").strip().lower()
    if ctype == "image/jpg":
        ctype = "image/jpeg"
    by_type = {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
        "image/gif": "gif",
    }
    ext = by_type.get(ctype)
    if ext:
        return ext
    guessed = mimetypes.guess_extension(ctype) if ctype else None
    if guessed:
        return guessed.lstrip(".")
    fallback_ext = os.path.splitext(str(fallback_name or ""))[1].lstrip(".").lower()
    return fallback_ext or "bin"


class _MemoryObject(BytesIO):
    def __init__(self, data: bytes, content_type: str):
        super().__init__(data)
        self.content_type = content_type


class R2Storage:
    def __init__(self):
        self.enabled = _truthy(os.getenv("R2_ENABLED"))
        self.account_id = str(os.getenv("R2_ACCOUNT_ID") or "").strip()
        self.bucket = str(os.getenv("R2_BUCKET") or os.getenv("R2_BUCKET_NAME") or "").strip()
        self.access_key_id = str(os.getenv("R2_ACCESS_KEY_ID") or "").strip()
        self.secret_access_key = str(os.getenv("R2_SECRET_ACCESS_KEY") or "").strip()
        endpoint_env = str(os.getenv("R2_ENDPOINT") or "").strip().rstrip("/")
        if not endpoint_env and self.account_id:
            endpoint_env = f"https://{self.account_id}.r2.cloudflarestorage.com"
        if self.bucket and endpoint_env.endswith(f"/{self.bucket}"):
            endpoint_env = endpoint_env[: -(len(self.bucket) + 1)]
        self.endpoint = endpoint_env
        self.public_base = _normalize_public_base(
            os.getenv("R2_PUBLIC_BASE_URL")
            or os.getenv("R2_PUBLIC_URL")
            or os.getenv("R2_PUBLIC_DOMAIN")
            or os.getenv("R2_CUSTOM_DOMAIN")
            or os.getenv("R2_PUBLIC_DEV_URL")
            or ""
        )
        self.prefix_characters = _clean_prefix(os.getenv("R2_PREFIX_CHARACTERS"), "characters")
        self.prefix_campaigns = _clean_prefix(os.getenv("R2_PREFIX_CAMPAIGNS"), "campaigns")
        self.prefix_wiki = _clean_prefix(os.getenv("R2_PREFIX_WIKI"), "wiki")
        self._client = None

    def is_ready(self) -> bool:
        if not self.enabled:
            return False
        if not boto3:
            return False
        required = [self.bucket, self.endpoint, self.access_key_id, self.secret_access_key]
        if not all(required):
            return False
        if self._client is None:
            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                region_name="auto",
            )
        return True

    def _join_key(self, *parts: str) -> str:
        return "/".join([str(p).strip().strip("/") for p in parts if str(p or "").strip()])

    def key_for_character_avatar(self, collection_name: str, character_id: str, content_type: str | None) -> str:
        ext = _extension_from_content_type(content_type)
        return self._join_key(
            self.prefix_characters,
            _safe_segment(collection_name),
            _safe_segment(character_id),
            f"avatar.{ext}",
        )

    def key_for_campaign_avatar(self, campaign_id: str, content_type: str | None) -> str:
        ext = _extension_from_content_type(content_type)
        return self._join_key(
            self.prefix_campaigns,
            _safe_segment(campaign_id),
            f"avatar.{ext}",
        )

    def key_for_wiki_asset(self, asset_id: str, filename: str = "", content_type: str | None = None) -> str:
        ext = _extension_from_content_type(content_type, fallback_name=filename)
        return self._join_key(self.prefix_wiki, _safe_segment(asset_id), f"asset.{ext}")

    def put_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str | None = None,
        cache_control: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.is_ready():
            raise RuntimeError("R2 is not configured")
        params: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": data,
        }
        if content_type:
            params["ContentType"] = content_type
        if cache_control:
            params["CacheControl"] = cache_control
        if metadata:
            params["Metadata"] = {str(k): str(v) for k, v in metadata.items()}
        self._client.put_object(**params)

    def get_file(self, key: str):
        if not self.is_ready():
            raise KeyError
        obj = self._client.get_object(Bucket=self.bucket, Key=key)
        body = obj["Body"].read()
        content_type = obj.get("ContentType") or "application/octet-stream"
        return _MemoryObject(body, content_type)

    def get_bytes(self, key: str) -> tuple[bytes, str]:
        fh = self.get_file(key)
        return fh.read(), fh.content_type or "application/octet-stream"

    def delete(self, key: str) -> None:
        if not self.is_ready():
            return
        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        except Exception:
            pass

    def public_url(self, key: str) -> str | None:
        if not self.public_base:
            return None
        return f"{self.public_base}/{quote(str(key or '').strip(), safe='/')}"
