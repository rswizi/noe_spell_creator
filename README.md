# NoE Spell Creator

## Local backend run

1. Install Python dependencies:
   - `pip install -r requirements.txt`
2. Configure env vars (minimum):
   - `MONGODB_URI` (example local test: `mongomock://localhost`, production: Atlas URI)
   - `CORS_ORIGINS` (mandatory in production)
3. Optional wiki/env settings:
   - `WIKI_ENABLED` (`true`/`false`, default `true`)
   - `WIKI_REQUIRE_AUTH` (`true`/`false`, default `true`)
   - `WIKI_STRICT_STARTUP` (`true` fails startup on wiki env errors)
   - `WIKI_MAX_DOC_BYTES` (default `200000`)
   - `WIKI_DEFAULT_VIEW_ROLES` (default `viewer,editor,admin`)
   - `WIKI_DEFAULT_EDIT_ROLES` (default `editor,admin`)
4. Start server:
   - `uvicorn main:app --reload --host 0.0.0.0 --port 8000`

## Wiki storage architecture

- Wiki is Mongo-backed (`wiki_categories`, `wiki_pages`, `wiki_page_content`, `wiki_page_revisions`, `wiki_links`, `wiki_relations`, `wiki_assets`, `wiki_entity_templates`).
- Startup validates wiki env contract and ensures validators/indexes.
- Page ACL uses defaults unless `acl_override=true` on a page.
- Roles:
  - app `user` -> wiki `viewer`
  - app `moderator` -> wiki `editor`
  - app `admin` -> wiki `admin`
  - optional per-user `users.wiki_role` override (`viewer|editor|admin`)

## Wiki API (current)

- Categories:
  - `GET /api/wiki/categories`
  - `POST /api/wiki/categories` (admin)
  - `PUT /api/wiki/categories/{category_id}` (admin)
  - `DELETE /api/wiki/categories/{category_id}` (admin)
- Entity templates:
  - `GET /api/wiki/templates`
  - `POST /api/wiki/templates` (admin)
  - `PUT /api/wiki/templates/{template_id}` (admin)
  - `DELETE /api/wiki/templates/{template_id}` (admin)
- Pages:
  - `POST /api/wiki/pages` (editor+)
  - `PUT /api/wiki/pages/{id}` (editor+ with ACL)
  - `PATCH /api/wiki/pages/{id}/fields` (editor+ with ACL)
  - `DELETE /api/wiki/pages/{id}` (editor+ with ACL)
  - `GET /api/wiki/pages`
  - `GET /api/wiki/pages/{id}`
  - `GET /api/wiki/pages/slug/{slug}`
  - `PUT /api/wiki/pages/{id}/acl` (admin)
  - `GET /api/wiki/me`
- Search/resolve:
  - `GET /api/wiki/resolve?query=...`
- Links/backlinks:
  - `POST /api/wiki/pages/{id}/links/rebuild`
  - `GET /api/wiki/pages/{id}/links`
  - `GET /api/wiki/pages/{id}/backlinks`
  - `GET /api/wiki/pages/{id}/context`
- Revisions:
  - `POST /api/wiki/pages/{id}/revisions`
  - `GET /api/wiki/pages/{id}/revisions`
  - `POST /api/wiki/pages/{id}/revisions/{revision_id}/restore`
- Relations:
  - `POST /api/wiki/pages/{id}/relations`
  - `GET /api/wiki/pages/{id}/relations`
  - `DELETE /api/wiki/relations/{relation_id}`

## Wiki frontend

Path: `frontend/wiki`

1. `cd frontend/wiki`
2. `npm install`
3. `npm run dev` (or `npm run build`)

FastAPI serves built assets from `/wiki` when `frontend/wiki/dist` exists.

- Admin panel route: `/wiki/admin` (category/template management, admin-only behavior).

## Assets and R2

- Upload endpoint: `POST /api/assets/upload` (editor+)
- Fetch endpoint: `GET /api/assets/{asset_id}`
- Storage:
  - R2 if configured (`R2_ENABLED=true` + R2 credentials/env)
  - fallback to GridFS / mongomock store

## Tests

- Run:
  - `python -m pytest -q tests/test_wiki_api.py tests/test_assets.py`
- Tests use `mongomock://localhost` and session-token auth fixtures.

## One-shot migration

- Legacy SQL wiki to Mongo migration script:
  - `python scripts/migrate_wiki_sql_to_mongo.py --sqlite-path wiki.db`
  - optional dry run: `python scripts/migrate_wiki_sql_to_mongo.py --sqlite-path wiki.db --dry-run`
