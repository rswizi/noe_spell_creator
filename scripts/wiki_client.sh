#!/bin/bash
set -euo pipefail
BASE="${BASE:-http://localhost:8000}"
TOKEN="${TOKEN:-test-token}"
HEADER="Authorization: Bearer ${TOKEN}"

echo "Creating page..."
PAGE=$(curl -sS -X POST "${BASE}/api/wiki/pages" \
  -H "${HEADER}" \
  -H "Content-Type: application/json" \
  -d '{"title":"Proof Page","slug":"proof-page","doc_json":{"type":"doc","content":[{"type":"paragraph","text":"Demo"}]}}' \
  | jq -c '.')

echo "Page created: ${PAGE}"
PAGE_ID=$(echo "${PAGE}" | jq -r '.id')

echo "Updating doc_json..."
curl -sS -X PUT "${BASE}/api/wiki/pages/${PAGE_ID}" \
  -H "${HEADER}" \
  -H "Content-Type: application/json" \
  -d '{"title":"Proof Page","slug":"proof-page","doc_json":{"type":"doc","content":[{"type":"paragraph","text":"Updated"}]}}' \
  | jq

echo "Creating revision..."
curl -sS -X POST "${BASE}/api/wiki/pages/${PAGE_ID}/revisions" -H "${HEADER}"
