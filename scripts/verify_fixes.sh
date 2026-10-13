#!/bin/bash
# MEMAR verify_fixes.sh — Smoke test with authentication
# Verifies: server health, auth works, protected endpoints require tokens
#
# Prerequisites:
#   - MEMAR backend running (uvicorn app.main:app on some port)
#   - curl, jq installed
#
# Usage:
#   bash scripts/verify_fixes.sh                    # Use default localhost:8000
#   BASE_URL=http://localhost:9000 bash scripts/verify_fixes.sh
#   MEMAR_ADMIN_PASSWORD=mypass bash scripts/verify_fixes.sh
#
# Running the server:
#   docker compose up -d                            # Ensure port 9000 is available
#   # OR manually:
#   cd backend && pip install -r requirements.txt
#   uvicorn app.main:app --host 0.0.0.0 --port 8000

set -e

BASE_URL="${BASE_URL:-http://localhost:8000}"
ADMIN_USER="${MEMAR_ADMIN_USER:-admin}"
ADMIN_PASSWORD="${MEMAR_ADMIN_PASSWORD:-test}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "═════════════════════════════════════════════════════════"
echo "MEMAR Smoke Test (with Auth)"
echo "═════════════════════════════════════════════════════════"
echo "Base URL: $BASE_URL"
echo ""

# Helper functions
check_status() {
    local name="$1"
    local expected="$2"
    local actual="$3"

    if [ "$actual" = "$expected" ]; then
        echo -e "${GREEN}✓ $name${NC}"
        return 0
    else
        echo -e "${RED}✗ $name (expected: $expected, got: $actual)${NC}"
        return 1
    fi
}

check_json_field() {
    local name="$1"
    local field="$2"
    local response="$3"
    local value

    value=$(echo "$response" | jq -r "$field" 2>/dev/null || echo "null")
    if [ "$value" != "null" ] && [ ! -z "$value" ]; then
        echo -e "${GREEN}✓ $name${NC}"
        return 0
    else
        echo -e "${RED}✗ $name (field not found: $field)${NC}"
        return 1
    fi
}

# Track failures
FAILED=0

# ─────────────────────────────────────────────────────────────
# Step 1: Check Server Health (public endpoints)
# ─────────────────────────────────────────────────────────────
echo "Step 1: Server Health Checks"
echo "────────────────────────────"

# Healthz
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/healthz")
HTTP_CODE=$(echo "$RESPONSE" | tail -n 1)
BODY=$(echo "$RESPONSE" | head -n -1)
check_status "GET /api/healthz" "200" "$HTTP_CODE" || ((FAILED++))

# Readyz
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/readyz")
HTTP_CODE=$(echo "$RESPONSE" | tail -n 1)
BODY=$(echo "$RESPONSE" | head -n -1)
check_status "GET /api/readyz" "200" "$HTTP_CODE" || ((FAILED++))

# Version
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/version")
HTTP_CODE=$(echo "$RESPONSE" | tail -n 1)
BODY=$(echo "$RESPONSE" | head -n -1)
check_status "GET /api/version" "200" "$HTTP_CODE" || ((FAILED++))

# License status
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/license/status")
HTTP_CODE=$(echo "$RESPONSE" | tail -n 1)
BODY=$(echo "$RESPONSE" | head -n -1)
check_status "GET /api/license/status" "200" "$HTTP_CODE" || ((FAILED++))

echo ""

# ─────────────────────────────────────────────────────────────
# Step 2: Login & Extract Token
# ─────────────────────────────────────────────────────────────
echo "Step 2: Authentication"
echo "─────────────────────"

LOGIN_RESPONSE=$(curl -s -w "\n%{http_code}" \
    -X POST "$BASE_URL/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASSWORD\"}")

HTTP_CODE=$(echo "$LOGIN_RESPONSE" | tail -n 1)
BODY=$(echo "$LOGIN_RESPONSE" | head -n -1)

if [ "$HTTP_CODE" = "200" ]; then
    echo -e "${GREEN}✓ POST /api/auth/login${NC}"
    TOKEN=$(echo "$BODY" | jq -r '.access_token' 2>/dev/null)
    if [ ! -z "$TOKEN" ] && [ "$TOKEN" != "null" ]; then
        echo -e "${GREEN}✓ Access token extracted${NC}"
        TOKEN_PREVIEW="${TOKEN:0:20}..."
        echo "  Token: $TOKEN_PREVIEW"
    else
        echo -e "${RED}✗ Failed to extract access_token from response${NC}"
        echo "  Response: $BODY"
        ((FAILED++))
        exit 1
    fi
else
    echo -e "${RED}✗ POST /api/auth/login (HTTP $HTTP_CODE)${NC}"
    echo "  Response: $BODY"
    ((FAILED++))
    exit 1
fi

AUTH_HEADER="Authorization: Bearer $TOKEN"
echo ""

# ─────────────────────────────────────────────────────────────
# Step 3: Protected Endpoints (with auth)
# ─────────────────────────────────────────────────────────────
echo "Step 3: Protected Endpoints (with Bearer token)"
echo "──────────────────────────────────────────────"

# GET /api/auth/me
RESPONSE=$(curl -s -w "\n%{http_code}" \
    -H "$AUTH_HEADER" \
    "$BASE_URL/api/auth/me")
HTTP_CODE=$(echo "$RESPONSE" | tail -n 1)
BODY=$(echo "$RESPONSE" | head -n -1)
check_status "GET /api/auth/me" "200" "$HTTP_CODE" || ((FAILED++))

# GET /api/printers
RESPONSE=$(curl -s -w "\n%{http_code}" \
    -H "$AUTH_HEADER" \
    "$BASE_URL/api/printers")
HTTP_CODE=$(echo "$RESPONSE" | tail -n 1)
BODY=$(echo "$RESPONSE" | head -n -1)
check_status "GET /api/printers" "200" "$HTTP_CODE" || ((FAILED++))

# GET /api/metrics
RESPONSE=$(curl -s -w "\n%{http_code}" \
    -H "$AUTH_HEADER" \
    "$BASE_URL/api/metrics")
HTTP_CODE=$(echo "$RESPONSE" | tail -n 1)
BODY=$(echo "$RESPONSE" | head -n -1)
check_status "GET /api/metrics" "200" "$HTTP_CODE" || ((FAILED++))

echo ""

# ─────────────────────────────────────────────────────────────
# Step 4: Auth Denial (without token)
# ─────────────────────────────────────────────────────────────
echo "Step 4: Verify Protected Endpoints Deny Unauthenticated"
echo "──────────────────────────────────────────────────────"

# GET /api/printers without auth should be 401
RESPONSE=$(curl -s -w "\n%{http_code}" "$BASE_URL/api/printers")
HTTP_CODE=$(echo "$RESPONSE" | tail -n 1)
BODY=$(echo "$RESPONSE" | head -n -1)
check_status "GET /api/printers (no auth) rejects with 401" "401" "$HTTP_CODE" || ((FAILED++))

echo ""

# ─────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────
echo "═════════════════════════════════════════════════════════"
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All checks passed${NC}"
    echo "═════════════════════════════════════════════════════════"
    exit 0
else
    echo -e "${RED}✗ $FAILED check(s) failed${NC}"
    echo "═════════════════════════════════════════════════════════"
    exit 1
fi
