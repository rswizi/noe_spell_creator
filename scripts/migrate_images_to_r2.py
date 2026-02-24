#!/usr/bin/env python
"""
One-shot migration: Mongo/GridFS images -> Cloudflare R2.

Scopes:
  - characters (legacy + 0.3.5 avatar files from GridFS/avatar_id)
  - campaigns  (binary avatar field on campaigns docs)
  - wiki       (wiki_assets_files GridFS + wiki_assets_meta)

Usage examples:
  python scripts/migrate_images_to_r2.py --dry-run
  python scripts/migrate_images_to_r2.py --only characters --only campaigns
  python scripts/migrate_images_to_r2.py --force

Notes:
  - Idempotent by default (skips records already having R2 keys).
  - Non-destructive: legacy Mongo/GridFS data is kept.
  - Requires R2 env vars and boto3 (see server/src/modules/r2_storage.py).
"""

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path
from typing import Any

import gridfs
from bson import ObjectId
from bson.binary import Binary

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db_mongo import get_col, get_db  # noqa: E402
from server.src.modules.r2_storage import R2Storage  # noqa: E402


def now_iso() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"


def to_bytes(value: Any) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    if isinstance(value, Binary):
        return bytes(value)
    if isinstance(value, memoryview):
        return value.tobytes()
    try:
        return bytes(value)
    except Exception:
        return b""


def detect_content_type(data: bytes, fallback: str = "application/octet-stream") -> str:
    if not data:
        return fallback
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return fallback


def migrate_character_avatars(storage: R2Storage, dry_run: bool, force: bool) -> dict[str, int]:
    db = get_db()
    fs = gridfs.GridFS(db)
    counts = {"scanned": 0, "migrated": 0, "skipped": 0, "errors": 0}
    for collection_name in ("characters", "characters_0_3_5"):
        col = get_col(collection_name)
        for ch in col.find({}, {"_id": 0, "id": 1, "avatar_id": 1, "avatar_r2_key": 1}):
            counts["scanned"] += 1
            cid = str(ch.get("id") or "").strip()
            av_id = str(ch.get("avatar_id") or "").strip()
            av_r2 = str(ch.get("avatar_r2_key") or "").strip()
            if not cid or not av_id:
                counts["skipped"] += 1
                continue
            if av_r2 and not force:
                counts["skipped"] += 1
                continue
            try:
                fh = fs.get(ObjectId(av_id))
                data = fh.read()
                content_type = str(getattr(fh, "content_type", "") or "").strip().lower()
                if content_type == "image/jpg":
                    content_type = "image/jpeg"
                if not content_type:
                    content_type = detect_content_type(data, fallback="image/png")
                r2_key = storage.key_for_character_avatar(collection_name, cid, content_type)
                if not dry_run:
                    storage.put_bytes(
                        r2_key,
                        data,
                        content_type=content_type,
                        cache_control="public, max-age=31536000, immutable",
                        metadata={"character_id": cid, "collection": collection_name},
                    )
                    col.update_one(
                        {"id": cid},
                        {
                            "$set": {
                                "avatar_r2_key": r2_key,
                                "avatar_content_type": content_type,
                                "updated_at": now_iso(),
                            }
                        },
                    )
                counts["migrated"] += 1
            except Exception as exc:
                counts["errors"] += 1
                print(f"[ERR] character avatar migrate failed ({collection_name}:{cid}): {exc}")
    return counts


def migrate_campaign_avatars(storage: R2Storage, dry_run: bool, force: bool) -> dict[str, int]:
    col = get_col("campaigns")
    counts = {"scanned": 0, "migrated": 0, "skipped": 0, "errors": 0}
    for doc in col.find({}, {"_id": 0, "id": 1, "avatar": 1, "avatar_r2_key": 1, "avatar_content_type": 1}):
        counts["scanned"] += 1
        cid = str(doc.get("id") or "").strip()
        blob = to_bytes(doc.get("avatar"))
        av_r2 = str(doc.get("avatar_r2_key") or "").strip()
        if not cid or not blob:
            counts["skipped"] += 1
            continue
        if av_r2 and not force:
            counts["skipped"] += 1
            continue
        try:
            content_type = str(doc.get("avatar_content_type") or "").strip().lower()
            if content_type == "image/jpg":
                content_type = "image/jpeg"
            if not content_type:
                content_type = detect_content_type(blob, fallback="image/png")
            r2_key = storage.key_for_campaign_avatar(cid, content_type)
            if not dry_run:
                storage.put_bytes(
                    r2_key,
                    blob,
                    content_type=content_type,
                    cache_control="public, max-age=31536000, immutable",
                    metadata={"campaign_id": cid},
                )
                col.update_one(
                    {"id": cid},
                    {
                        "$set": {
                            "avatar_r2_key": r2_key,
                            "avatar_content_type": content_type,
                            "updated_at": now_iso(),
                        }
                    },
                )
            counts["migrated"] += 1
        except Exception as exc:
            counts["errors"] += 1
            print(f"[ERR] campaign avatar migrate failed ({cid}): {exc}")
    return counts


def migrate_wiki_assets(storage: R2Storage, dry_run: bool, force: bool) -> dict[str, int]:
    db = get_db()
    fs = gridfs.GridFS(db, collection="wiki_assets_files")
    meta_col = db.get_collection("wiki_assets_meta")
    counts = {"scanned": 0, "migrated": 0, "skipped": 0, "errors": 0}
    for meta in meta_col.find({}, {"_id": 0, "asset_id": 1, "filename": 1, "mime": 1, "r2_key": 1}):
        counts["scanned"] += 1
        asset_id = str(meta.get("asset_id") or "").strip()
        r2_key_existing = str(meta.get("r2_key") or "").strip()
        if not asset_id:
            counts["skipped"] += 1
            continue
        if r2_key_existing and not force:
            counts["skipped"] += 1
            continue
        try:
            fh = fs.get(ObjectId(asset_id))
            data = fh.read()
            content_type = str(getattr(fh, "content_type", "") or meta.get("mime") or "").strip().lower()
            if content_type == "image/jpg":
                content_type = "image/jpeg"
            if not content_type:
                content_type = detect_content_type(data, fallback="application/octet-stream")
            filename = str(meta.get("filename") or getattr(fh, "filename", "") or "asset")
            r2_key = storage.key_for_wiki_asset(asset_id, filename=filename, content_type=content_type)
            if not dry_run:
                storage.put_bytes(
                    r2_key,
                    data,
                    content_type=content_type,
                    cache_control="public, max-age=31536000, immutable",
                    metadata={"asset_id": asset_id},
                )
                meta_col.update_one({"asset_id": asset_id}, {"$set": {"r2_key": r2_key}})
            counts["migrated"] += 1
        except Exception as exc:
            counts["errors"] += 1
            print(f"[ERR] wiki asset migrate failed ({asset_id}): {exc}")
    return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate Mongo/GridFS image storage to R2")
    parser.add_argument(
        "--only",
        action="append",
        choices=("characters", "campaigns", "wiki"),
        help="Run only selected scope(s). Can be repeated.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview only; do not upload or write DB updates.")
    parser.add_argument("--force", action="store_true", help="Re-upload even if r2 key already exists.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scopes = set(args.only or ["characters", "campaigns", "wiki"])
    storage = R2Storage()
    if not storage.is_ready():
        print("[ERR] R2 is not configured or not ready. Check env vars and boto3.")
        print("Required: R2_ENABLED=true, R2_BUCKET, R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY")
        return 2

    print(f"[INFO] Starting migration | scopes={sorted(scopes)} | dry_run={args.dry_run} | force={args.force}")
    results: dict[str, dict[str, int]] = {}

    if "characters" in scopes:
        print("[INFO] Migrating character avatars...")
        results["characters"] = migrate_character_avatars(storage, args.dry_run, args.force)
    if "campaigns" in scopes:
        print("[INFO] Migrating campaign avatars...")
        results["campaigns"] = migrate_campaign_avatars(storage, args.dry_run, args.force)
    if "wiki" in scopes:
        print("[INFO] Migrating wiki assets...")
        results["wiki"] = migrate_wiki_assets(storage, args.dry_run, args.force)

    print("\n[SUMMARY]")
    total_errors = 0
    for scope, stats in results.items():
        total_errors += int(stats.get("errors", 0))
        print(
            f"- {scope}: scanned={stats.get('scanned', 0)} migrated={stats.get('migrated', 0)} "
            f"skipped={stats.get('skipped', 0)} errors={stats.get('errors', 0)}"
        )
    print("[DONE]")
    return 1 if total_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
