#!/bin/bash
# ServerStick Pi Agent — Development Start Script
# Runs on any Debian 12+ machine for testing.
#
# Usage:
#   ./dev-start.sh          # Start agent + dashboard dev server
#   ./dev-start.sh --api    # API only (no Svelte HMR)
#   ./dev-start.sh --build  # Build dashboard, then start API serving static

set -euo pipefail
cd "$(dirname "$0")"

AGENT_DIR="$(pwd)"
VENV_DIR="$AGENT_DIR/.venv"
DASHBOARD_DIR="$AGENT_DIR/dashboard"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}🖥️  ServerStick Pi Agent — Dev Mode${NC}"

# ─── Virtual Environment ─────────────────────────────────────────────

if [ ! -f "$VENV_DIR/bin/python3" ]; then
    echo -e "${YELLOW}Creating venv...${NC}"
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -q fastapi 'uvicorn[standard]' httpx pydantic pyyaml
fi

# ─── Mode Selection ──────────────────────────────────────────────────

MODE="${1:---all}"

case "$MODE" in
    --api)
        echo -e "${GREEN}Starting API server only...${NC}"
        echo "  Dashboard at: http://localhost:8080 (static or placeholder)"
        "$VENV_DIR/bin/python3" -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload
        ;;

    --build)
        echo -e "${YELLOW}Building Svelte dashboard...${NC}"
        cd "$DASHBOARD_DIR"
        npm run build
        cd "$AGENT_DIR"
        echo -e "${GREEN}Starting API server with built dashboard...${NC}"
        echo "  Dashboard at: http://localhost:8080"
        "$VENV_DIR/bin/python3" -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload
        ;;

    --all|*)
        echo -e "${GREEN}Starting in split mode:${NC}"
        echo "  API:      http://localhost:8080"
        echo "  Dashboard: http://localhost:5173 (Svelte HMR → proxied to API)"
        echo ""
        echo -e "${YELLOW}Starting Svelte dev server...${NC}"
        cd "$DASHBOARD_DIR"
        npx vite dev --port 5173 &
        VITE_PID=$!
        
        cd "$AGENT_DIR"
        echo -e "${YELLOW}Starting FastAPI...${NC}"
        "$VENV_DIR/bin/python3" -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload &
        API_PID=$!
        
        echo ""
        echo -e "${GREEN}Both servers running. Press Ctrl+C to stop.${NC}"
        
        # Wait for either process to exit
        wait -n $VITE_PID $API_PID 2>/dev/null || true
        kill $VITE_PID $API_PID 2>/dev/null
        ;;
esac