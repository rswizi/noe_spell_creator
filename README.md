# NoE Spell Creator

## Running the server locally

1. Install dependencies: `pip install -r requirements.txt`
   - This pulls in `asyncpg`, `aiosqlite`, `python-multipart`, SQLAlchemy, and the testing stack used for the wiki slice.
2. Set the required environment variables:
   - `DATABASE_URL` (Postgres: `postgresql+asyncpg://user:pass@host/db`; SQLite for local dev: `sqlite+aiosqlite:///./wiki.db`)
   - `API_TOKEN` (must be set in prod; development environments warn but still run)
   - `CORS_ORIGINS` (comma-separated list of allowed origins; mandatory in production)
   - Optional: `WIKI_MAX_DOC_BYTES` caps the serialized JSON payload (default 200000 bytes)
3. Run migrations: `alembic upgrade head`
4. Start the app: `uvicorn main:app --reload --host 0.0.0.0 --port 8000`

## Wiki frontend (Milestone 2)

1. Enter `frontend/wiki` and run `npm install` to pull the React + TipTap stack.
2. For development, run `npm run dev` and open the `/wiki` path from the dev server.
3. Build the static files: `npm run build` (output lands under `frontend/wiki/dist`).
4. FastAPI automatically serves `/wiki` with the built assets, so redeploy after building to update the SPA.
5. Configure `VITE_API_BASE_URL` (defaults to same origin) and dev-only `VITE_API_TOKEN` when running locally.
6. Use the toolbar TOC button or `/` slash command to drop a Table of Contents block; headings now generate stable slug anchors so the sidebar links stay valid.
7. Type `[[` to open the internal link palette. The UI hits `GET /api/wiki/resolve?query=…` (title/slug search, default 10 results, max 25) and stores the referenced page slug/ID plus fragment for future rename/backlink support.
8. Tables now work out of the box: use the Table button to open the 2×2–10×10 grid picker, then manage rows/columns via the floating menu that appears while editing a table. Columns are resizable by drag and the read-only renderer keeps them styled consistently.

## Wiki API slice (Milestone 1)

- Postgres-backed models:
  - `wiki_pages` (id, slug, title, doc_json, created_at, updated_at; JSONB on Postgres, JSON on SQLite)
  - `wiki_revisions` (id, page_id, doc_json, title, slug, created_at)
- Read endpoints (list, retrieve by id/slug, `/resolve`, and revisions retrieval) are public for rendering. Creation, updates, and revisions snapshots use the `require_wiki_admin` guard so only admin/moderator sessions or the API token can mutate state.
- `GET /api/wiki/resolve?query=…` performs case-insensitive title/slug matching, prefers exact title hits, caps results at 25, and powers the internal link picker.
- Configurable CORS and automatic slug/size rejection guard the canonical document storage.
- `scripts/wiki_client.sh` demonstrates create → update → revision using the token-based auth.

## Testing

- Run `python -m pytest tests/test_wiki_api.py` after installing dependencies to exercise the wiki CRUD + revision flows, slug enforcement, and authentication guardrails.

## Alembic migrations

- Controlled via `alembic.ini`/`alembic/env.py`. The env script derives a sync URL (using `DATABASE_SYNC_URL` or falling back to the async URL with `psycopg2`/`sqlite` variants).
- Run `alembic upgrade head` any time the schema changes; it creates/updates the `wiki_pages` and `wiki_revisions` tables plus the `updated_at` index on `wiki_pages`.

## Render deployment notes

- Environment variables:
- `DATABASE_URL` (use the managed Postgres URL and include `postgresql+asyncpg` as the scheme)
- `API_TOKEN` (random bearer token that secures `/api/wiki/*`)
- `CORS_ORIGINS` (e.g., `https://your-frontend.onrender.com`)
- Optional: `WIKI_MAX_DOC_BYTES`
- `MONGODB_URI` (used for GridFS image storage; set to `mongomock://localhost` for local tests or your Atlas URL in production)
- `DB_NAME` (optional override when your URI doesn't already encode `NoeSpellCreator`; defaults to that name if unspecified)
- `ASSETS_MAX_UPLOAD_MB` (defaults to `10`; caps image uploads in the browser)
Images are uploaded by admins/moderators via `/api/assets/upload` (tooling enforces the same `API_TOKEN`/session guard), then served at `/api/assets/{asset_id}` with long cache headers.

## Wiki editor image workflow
1. Use the Image button, drop, or paste to add an image.
2. Uploads automatically POST to the asset endpoint, store GridFS metadata, and insert nodes with `asset_id`, caption, and sizing attributes.
3. The floating toolbar lets you adjust width, alignment, or caption without triggering extra autosaves.
- Recommended start command: `pip install -r requirements.txt && alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port $PORT`
- Recommended Render build pipeline: `pip install -r requirements.txt && cd frontend/wiki && npm install && npm run build`

## Tips

- Always run `alembic upgrade head` before the app boots on Render or locally; the async session assumes the tables and indexes exist.

## Proof-of-life client

Use the helper script with `BASE`/`TOKEN` to confirm API connectivity:

```
BASE=http://localhost:8000 TOKEN=supersecret bash scripts/wiki_client.sh
```

Requires `jq` plus the API token configured above.

## Next steps (Milestone 2)

1. Build the TipTap-powered rich text editor + read-mode renderer.
2. Hook autosave to `PUT /api/wiki/pages/{id}`.
3. Add tables, images, TOC, and the internal link resolver/block support.
4. Implement presigned image uploads, asset metadata, and `/resolve` for wiki intra-links.
