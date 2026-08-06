#!/bin/bash
# Integration tests for Cortex Workflow Service
# Usage: HOST=http://localhost:8001 ./run_tests.sh
set -euo pipefail

HOST="${HOST:-http://localhost:8001}"
PASS=0
FAIL=0
JWT=""

setup_jwt() {
    JWT=$(python3 -c "
import jwt, uuid, time
payload = {'sub': 'aaa352bb-8035-4e76-88d7-9813e84b966b', 'email': 'test@test.com', 'exp': 9999999999, 'iat': int(time.time())}
print(jwt.encode(payload, 'change-this-in-production-super-secret-key', algorithm='HS256'))
" 2>/dev/null || python3 -c "
from jose import jwt
import uuid, time
payload = {'sub': 'aaa352bb-8035-4e76-88d7-9813e84b966b', 'email': 'test@test.com', 'exp': 9999999999, 'iat': int(time.time())}
print(jwt.encode(payload, 'change-this-in-production-super-secret-key', algorithm='HS256'))
")
}

assert_status() {
    local label="$1" expected="$2" actual="$3" body="$4"
    if [ "$actual" = "$expected" ]; then
        echo "  PASS [$expected] $label"
        PASS=$((PASS + 1))
    else
        echo "  FAIL [expected=$expected got=$actual] $label"
        echo "    body: $(echo "$body" | head -c 200)"
        FAIL=$((FAIL + 1))
    fi
}

post_json() {
    local url="$1" data="$2" extra_header="${3:-}"
    if [ -n "$extra_header" ]; then
        curl -s -w "\n%{http_code}" -X POST "$HOST$url" \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer $JWT" \
            -H "$extra_header" \
            -d "$data"
    else
        curl -s -w "\n%{http_code}" -X POST "$HOST$url" \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer $JWT" \
            -d "$data"
    fi
}

get_json() {
    local url="$1" extra_headers="${2:-}"
    local cmd="curl -s -w \"\\n%{http_code}\" \"$HOST$url\""
    if [ -n "$extra_headers" ]; then
        for h in $extra_headers; do
            cmd="$cmd -H \"$h\""
        done
    else
        cmd="$cmd -H \"Authorization: Bearer $JWT\""
    fi
    eval "$cmd"
}

patch_json() {
    local url="$1" data="$2"
    curl -s -w "\n%{http_code}" -X PATCH "$HOST$url" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $JWT" \
        -d "$data"
}

delete_req() {
    curl -s -w "\n%{http_code}" -X DELETE "$HOST$url" \
        -H "Authorization: Bearer $JWT" 2>/dev/null
    local url="$1"
    curl -s -w "\n%{http_code}" -X DELETE "$HOST$url" \
        -H "Authorization: Bearer $JWT"
}

VALID_DEF='{"nodes":[{"id":"t1","type":"trigger.manual","position":{"x":0,"y":0},"data":{}},{"id":"a1","type":"action.create_note","position":{"x":200,"y":0},"data":{}}],"edges":[{"id":"e1","source":"t1","target":"a1"}],"variables":{}}'

WEBHOOK_DEF='{"nodes":[{"id":"t1","type":"trigger.webhook","position":{"x":0,"y":0},"data":{}},{"id":"a1","type":"action.create_note","position":{"x":200,"y":0},"data":{}}],"edges":[{"id":"e1","source":"t1","target":"a1"}],"variables":{}}'

echo "=== Setup ==="
setup_jwt
echo "JWT token generated"

echo ""
echo "=== 1. Health Check ==="
BODY=$(curl -s "$HOST/health")
echo "  $BODY"

echo ""
echo "=== 2. POST create workflow (internal_event) ==="
RESP=$(post_json "/api/v1/workflows" \
  "{\"name\":\"Test WF\",\"trigger_type\":\"internal_event\",\"trigger_config\":{\"event\":\"note.created\"},\"definition\":$VALID_DEF}")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | sed '$d')
WF_ID=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null || echo "")
assert_status "create internal_event workflow" 201 "$CODE" "$BODY"

echo ""
echo "=== 3. GET list workflows ==="
RESP=$(get_json "/api/v1/workflows")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | sed '$d')
TOTAL=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['total'])" 2>/dev/null || echo "err")
assert_status "list workflows" 200 "$CODE" "$BODY"
echo "    total=$TOTAL"

echo ""
echo "=== 4. GET workflow by id ==="
RESP=$(get_json "/api/v1/workflows/$WF_ID")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | sed '$d')
assert_status "get workflow by id" 200 "$CODE" "$BODY"

echo ""
echo "=== 5. Activate minimal (no trigger/action) -> 400 ==="
RESP=$(post_json "/api/v1/workflows" \
  "{\"name\":\"Min\",\"trigger_type\":\"manual\",\"definition\":{\"nodes\":[],\"edges\":[],\"variables\":{}}}")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | sed '$d')
MIN_ID=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null || echo "")
RESP=$(post_json "/api/v1/workflows/$MIN_ID/activate" "")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | sed '$d')
assert_status "activate minimal (400)" 400 "$CODE" "$BODY"

echo ""
echo "=== 6. Activate valid workflow ==="
RESP=$(post_json "/api/v1/workflows/$WF_ID/activate" "")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | sed '$d')
STATUS=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null || echo "err")
assert_status "activate workflow" 200 "$CODE" "$BODY"
echo "    status=$STATUS"

echo ""
echo "=== 7. Pause workflow ==="
RESP=$(post_json "/api/v1/workflows/$WF_ID/pause" "")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | sed '$d')
STATUS=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])" 2>/dev/null || echo "err")
assert_status "pause workflow" 200 "$CODE" "$BODY"
echo "    status=$STATUS"

echo ""
echo "=== 8. PATCH update workflow ==="
RESP=$(patch_json "/api/v1/workflows/$WF_ID" '{"name":"Updated Name"}')
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | sed '$d')
NAME=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['name'])" 2>/dev/null || echo "err")
assert_status "patch workflow" 200 "$CODE" "$BODY"
echo "    name=$NAME"

echo ""
echo "=== 9. No auth -> 403 ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$HOST/api/v1/workflows")
assert_status "no auth" 403 "$CODE" ""

echo ""
echo "=== 10. Wrong user -> 404 ==="
OTHER=$(python3 -c "
from jose import jwt
import uuid, time
print(jwt.encode({'sub': str(uuid.uuid4()), 'exp': 9999999999, 'iat': int(time.time())}, 'change-this-in-production-super-secret-key', algorithm='HS256'))
" 2>/dev/null || python3 -c "
import jwt, uuid, time
payload = {'sub': str(uuid.uuid4()), 'exp': 9999999999, 'iat': int(time.time())}
print(jwt.encode(payload, 'change-this-in-production-super-secret-key', algorithm='HS256'))
")
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$HOST/api/v1/workflows/$WF_ID" -H "Authorization: Bearer $OTHER")
assert_status "wrong user" 404 "$CODE" ""

echo ""
echo "=== 11. Soft delete -> 204 ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$HOST/api/v1/workflows/$WF_ID" -H "Authorization: Bearer $JWT")
assert_status "soft delete" 204 "$CODE" ""

echo ""
echo "=== 12. Deleted workflow -> 404 ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$HOST/api/v1/workflows/$WF_ID" -H "Authorization: Bearer $JWT")
assert_status "deleted workflow" 404 "$CODE" ""

echo ""
echo "=== 13. Create webhook workflow ==="
RESP=$(post_json "/api/v1/workflows" \
  "{\"name\":\"Webhook WF\",\"trigger_type\":\"webhook\",\"definition\":$WEBHOOK_DEF}")
CODE=$(echo "$RESP" | tail -1); BODY=$(echo "$RESP" | sed '$d')
WB_ID=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])" 2>/dev/null || echo "")
WB_URL=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['webhook_url'])" 2>/dev/null || echo "")
SECRET=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['webhook_secret'])" 2>/dev/null || echo "")
assert_status "create webhook workflow" 201 "$CODE" "$BODY"
echo "    webhook_url=$WB_URL has_secret=$(test -n "$SECRET" && echo yes || echo no)"

echo ""
echo "=== 14. Webhook without activation -> 409 ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$HOST$WB_URL" \
  -H "Content-Type: application/json" -d '{"test":true}')
assert_status "webhook not active" 409 "$CODE" ""

echo ""
echo "=== 15. Activate webhook workflow ==="
RESP=$(post_json "/api/v1/workflows/$WB_ID/activate" "")
CODE=$(echo "$RESP" | tail -1)
assert_status "activate webhook workflow" 200 "$CODE" "$(echo "$RESP" | sed '$d')"

echo ""
echo "=== 16. Webhook with correct secret -> 202 ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$HOST$WB_URL" \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: $SECRET" \
  -d '{"test":true}')
assert_status "webhook correct secret" 202 "$CODE" ""

echo ""
echo "=== 17. Webhook with wrong secret -> 401 ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$HOST$WB_URL" \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Secret: wrong-secret" \
  -d '{"test":true}')
assert_status "webhook wrong secret" 401 "$CODE" ""

echo ""
echo "=== 18. Webhook without secret -> 202 ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$HOST$WB_URL" \
  -H "Content-Type: application/json" \
  -d '{"test":true}')
assert_status "webhook no secret" 202 "$CODE" ""

echo ""
echo "=== 19. GET /api/v1/actions ==="
RESP=$(get_json "/api/v1/actions")
CODE=$(echo "$RESP" | tail -1)
ACTS=$(echo "$RESP" | sed '$d' | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'actions={len(d[\"actions\"])} triggers={len(d[\"triggers\"])}')" 2>/dev/null || echo "err")
assert_status "list actions" 200 "$CODE" "$(echo "$RESP" | sed '$d')"
echo "    $ACTS"

echo ""
echo "=== 20. Webhook not found -> 404 ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$HOST/api/v1/webhooks/nonexistentpath123456" \
  -H "Content-Type: application/json" -d '{"test":true}')
assert_status "webhook not found" 404 "$CODE" ""

echo ""
echo "========================================"
echo "Results: $PASS passed, $FAIL failed"
echo "========================================"
if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
