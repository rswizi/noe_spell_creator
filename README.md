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

## Wiki API slice (Milestone 1)

- Postgres-backed models:
  - `wiki_pages` (id, slug, title, doc_json, created_at, updated_at; JSONB on Postgres, JSON on SQLite)
  - `wiki_revisions` (id, page_id, doc_json, title, slug, created_at)
- Authenticated FastAPI endpoints under `/api/wiki` kitted with router-level token/session guards, slug validation, and JSON size limits.
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
- Recommended start command: `pip install -r requirements.txt && alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port $PORT`

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
