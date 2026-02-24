#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from server.src.modules.wiki_repo import WikiMongoRepo, ensure_wiki_collections_and_indexes
from server.src.modules.wiki_service import normalize_acl, utc_now


def _loads_doc(raw: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    text = str(raw or "").strip()
    if not text:
        return {"type": "doc", "content": []}
    try:
        return json.loads(text)
    except Exception:
        return {"type": "doc", "content": []}


def _fetch_rows(conn: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    cur = conn.execute(query)
    names = [meta[0] for meta in cur.description]
    out: list[dict[str, Any]] = []
    for row in cur.fetchall():
        out.append({names[idx]: row[idx] for idx in range(len(names))})
    return out


def migrate(sqlite_path: Path, dry_run: bool = False) -> None:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite file not found: {sqlite_path}")

    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    pages = _fetch_rows(
        conn,
        """
        SELECT id, slug, title, doc_json, created_at, updated_at
        FROM wiki_pages
        ORDER BY created_at ASC
        """,
    )
    revisions = _fetch_rows(
        conn,
        """
        SELECT id, page_id, title, slug, doc_json, created_at
        FROM wiki_revisions
        ORDER BY created_at ASC
        """,
    )
    conn.close()

    print(f"Found {len(pages)} pages and {len(revisions)} revisions in {sqlite_path}")
    if dry_run:
        print("Dry-run mode, no write performed.")
        return

    ensure_wiki_collections_and_indexes()
    repo = WikiMongoRepo()
    now = utc_now()
    migrated_pages = 0
    skipped_pages = 0
    for row in pages:
        page_id = str(row.get("id") or "").strip()
        slug = str(row.get("slug") or "").strip()
        title = str(row.get("title") or "").strip()
        if not page_id or not slug or not title:
            skipped_pages += 1
            continue
        if repo.pages.find_one({"id": page_id}, {"_id": 1}) or repo.pages.find_one({"slug": slug}, {"_id": 1}):
            skipped_pages += 1
            continue
        doc_json = _loads_doc(row.get("doc_json"))
        acl = normalize_acl(None)
        page_doc = {
            "id": page_id,
            "title": title,
            "slug": slug,
            "category_id": "general",
            "entity_type": None,
            "template_id": None,
            "fields": {},
            "summary": None,
            "tags": [],
            "status": "published",
            "created_by": "sql_migration",
            "updated_by": "sql_migration",
            "version": 1,
            "acl_override": False,
            "acl": {"view_roles": list(acl["view_roles"]), "edit_roles": list(acl["edit_roles"])},
            "created_at": row.get("created_at") or now,
            "updated_at": row.get("updated_at") or now,
        }
        content_doc = {
            "page_id": page_id,
            "doc_json": doc_json,
            "plain_text": "",
            "toc_snapshot": [],
            "version": 1,
            "updated_at": row.get("updated_at") or now,
        }
        repo.pages.insert_one(page_doc)
        repo.page_content.replace_one({"page_id": page_id}, content_doc, upsert=True)
        repo.rebuild_links_for_page(page_id)
        migrated_pages += 1

    migrated_revisions = 0
    skipped_revisions = 0
    for row in revisions:
        revision_id = str(row.get("id") or "").strip()
        page_id = str(row.get("page_id") or "").strip()
        if not revision_id or not page_id:
            skipped_revisions += 1
            continue
        if not repo.pages.find_one({"id": page_id}, {"_id": 1}):
            skipped_revisions += 1
            continue
        if repo.page_revisions.find_one({"id": revision_id}, {"_id": 1}):
            skipped_revisions += 1
            continue
        revision_doc = {
            "id": revision_id,
            "page_id": page_id,
            "version": 1,
            "doc_json": _loads_doc(row.get("doc_json")),
            "title": str(row.get("title") or ""),
            "slug": str(row.get("slug") or ""),
            "saved_by": "sql_migration",
            "saved_at": row.get("created_at") or now,
        }
        repo.page_revisions.insert_one(revision_doc)
        migrated_revisions += 1

    print(f"Migrated pages: {migrated_pages} (skipped {skipped_pages})")
    print(f"Migrated revisions: {migrated_revisions} (skipped {skipped_revisions})")


def main() -> None:
    parser = argparse.ArgumentParser(description="One-shot migration: legacy SQL wiki tables -> Mongo wiki collections.")
    parser.add_argument("--sqlite-path", default="wiki.db", help="Path to sqlite wiki DB file (default: wiki.db)")
    parser.add_argument("--dry-run", action="store_true", help="Only inspect source DB, do not write to Mongo")
    args = parser.parse_args()
    migrate(Path(args.sqlite_path), dry_run=bool(args.dry_run))


if __name__ == "__main__":
    main()
