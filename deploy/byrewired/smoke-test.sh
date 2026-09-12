#!/usr/bin/env bash
#
# Exercises a running ByRewired DB the way a person would: sign up, make a
# workspace, a database, a table, a field and a row, then read the row back.
#
#   bash smoke-test.sh https://db.example.com
#
# It creates a real account and a real workspace, so point it at a new
# deployment, or delete what it leaves behind afterwards. The account it makes
# is smoke+<timestamp>@byrewired.test.
#
# Behind Cloudflare Access the API is not reachable without a service token,
# so run this from the server itself against http://localhost before the
# Access policy is in the way:
#
#   bash smoke-test.sh http://localhost

set -euo pipefail

BASE="${1:-http://localhost}"
BASE="${BASE%/}"
API="$BASE/api"
EMAIL="smoke+$(date +%s)@byrewired.test"
PASSWORD="SmokeTest!2345"

step() { printf '\n\033[1m%s\033[0m\n' "$*"; }
json() { python3 -c "import json,sys; print(json.load(sys.stdin)$1)"; }

step "Health"
curl -fsS "$API/_health/" -o /dev/null -w 'health: %{http_code}\n'

step "Sign up"
curl -fsS -X POST "$API/user/" -H 'Content-Type: application/json' \
  -d "{\"name\":\"Smoke\",\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" \
  -o /dev/null -w 'signup: %{http_code}\n'

step "Sign in"
TOKEN=$(curl -fsS -X POST "$API/user/token-auth/" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" | json '["access_token"]')
[ -n "$TOKEN" ] || { echo "no token returned"; exit 1; }
echo "signed in"
AUTH="Authorization: JWT $TOKEN"

step "Workspace"
WS_ID=$(curl -fsS -X POST "$API/workspaces/" -H "$AUTH" \
  -H 'Content-Type: application/json' -d '{"name":"Smoke workspace"}' | json '["id"]')
echo "workspace $WS_ID"

step "Database"
DB_ID=$(curl -fsS -X POST "$API/applications/workspace/$WS_ID/" -H "$AUTH" \
  -H 'Content-Type: application/json' -d '{"name":"Smoke db","type":"database"}' \
  | json '["id"]')
echo "database $DB_ID"

step "Table"
TB_ID=$(curl -fsS -X POST "$API/database/tables/database/$DB_ID/" -H "$AUTH" \
  -H 'Content-Type: application/json' -d '{"name":"Tasks"}' | json '["id"]')
echo "table $TB_ID"

step "Field"
FD_ID=$(curl -fsS -X POST "$API/database/fields/table/$TB_ID/" -H "$AUTH" \
  -H 'Content-Type: application/json' -d '{"name":"Priority","type":"number"}' \
  | json '["id"]')
echo "field $FD_ID"

step "Row"
curl -fsS -X POST "$API/database/rows/table/$TB_ID/?user_field_names=true" -H "$AUTH" \
  -H 'Content-Type: application/json' -d '{"Priority":7}' \
  -o /dev/null -w 'create row: %{http_code}\n'

step "Read it back"
curl -fsS "$API/database/rows/table/$TB_ID/?user_field_names=true" -H "$AUTH" \
  | python3 -c '
import json,sys
d = json.load(sys.stdin)
# A new table comes with blank rows, so find the one that was just written.
mine = [r for r in d["results"] if r["Priority"] == "7"]
assert len(mine) == 1, d
print("Priority =", mine[0]["Priority"], "among", d["count"], "rows")
'

step "Views"
curl -fsS "$API/database/views/table/$TB_ID/" -H "$AUTH" | python3 -c '
import json,sys
print("view types:", ", ".join(sorted({v["type"] for v in json.load(sys.stdin)})) or "none")
'

step "Passed"
echo "Sign up, workspaces, databases, tables, fields and rows all work."
echo "Delete the smoke workspace when you are done with it."
