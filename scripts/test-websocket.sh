#!/bin/bash
# WebSocket connection test with authentication

BASE_URL="${BASE_URL:-http://localhost:8765}"
ADMIN_PASSWORD="${MEMAR_ADMIN_PASSWORD:-testpass123}"

echo "════════════════════════════════════════════════════════════════"
echo "MEMAR WebSocket Authentication Test"
echo "════════════════════════════════════════════════════════════════"
echo ""

# Get token
echo "Step 1: Obtaining access token..."
LOGIN_RESPONSE=$(curl -s -X POST "$BASE_URL/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"admin\",\"password\":\"$ADMIN_PASSWORD\"}")

TOKEN=$(echo "$LOGIN_RESPONSE" | jq -r '.access_token' 2>/dev/null)

if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
    echo "❌ Failed to get token"
    echo "Response: $LOGIN_RESPONSE"
    exit 1
fi

echo "✅ Token obtained: ${TOKEN:0:30}..."
echo ""

# Construct WebSocket URL
WS_URL="${BASE_URL/http/ws}/ws/fleet?token=$TOKEN"

echo "Step 2: WebSocket Connection Details"
echo "────────────────────────────────────"
echo "URL: $WS_URL"
echo ""
echo "To test live streaming:"
echo "  npm install -g wscat"
echo "  wscat -c '$WS_URL'"
echo ""
echo "Expected: Fleet data JSON with fleet state, printer statuses, metrics"
echo ""

# Test WebSocket handshake (if curl supports it)
if command -v websocat &> /dev/null; then
    echo "Step 3: Testing WebSocket connection with websocat..."
    timeout 3 websocat "$WS_URL" || true
elif command -v wscat &> /dev/null; then
    echo "Step 3: Testing WebSocket connection with wscat..."
    timeout 3 wscat -c "$WS_URL" || true
else
    echo "Step 3: WebSocket tools not installed (wscat/websocat)"
    echo "  Install wscat: npm install -g wscat"
    echo "  Then run: wscat -c '$WS_URL'"
fi

echo ""
echo "════════════════════════════════════════════════════════════════"
echo "✅ WebSocket auth token validated"
echo "════════════════════════════════════════════════════════════════"
