#!/usr/bin/env bash
#
# Reclaim Fi — n8n Workflow Orchestrator Setup
# Usage: bash setup.sh
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$SCRIPT_DIR/data"
ENV_FILE="$SCRIPT_DIR/.env"

echo "=== Reclaim Fi — n8n Setup ==="
echo ""

# 1. Create data directory
echo "[1/4] Creating data directory..."
mkdir -p "$DATA_DIR"

# 2. Generate secure password if .env doesn't exist
if [ -f "$ENV_FILE" ]; then
    echo "[2/4] .env already exists — keeping existing credentials"
    source "$ENV_FILE"
else
    echo "[2/4] Generating secure credentials..."
    N8N_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)
    cat > "$ENV_FILE" <<EOF
N8N_PASSWORD=$N8N_PASSWORD
EOF
    chmod 600 "$ENV_FILE"
    echo "    Credentials written to $ENV_FILE"
fi

# 3. Start n8n
echo "[3/4] Starting n8n with docker compose..."
cd "$SCRIPT_DIR"
docker compose up -d

# 4. Print access info
echo "[4/4] Done!"
echo ""
echo "================================================"
echo "  n8n is starting up..."
echo "================================================"
echo ""
echo "  URL:      http://135.181.61.221:5678"
echo "  User:     reclaim-admin"
echo "  Password: $N8N_PASSWORD"
echo ""
echo "  Credentials stored in: $ENV_FILE"
echo "  Data volume:           $DATA_DIR"
echo ""
echo "  Commands:"
echo "    Start:   cd $SCRIPT_DIR && docker compose up -d"
echo "    Stop:    cd $SCRIPT_DIR && docker compose down"
echo "    Logs:    cd $SCRIPT_DIR && docker compose logs -f"
echo "    Restart: cd $SCRIPT_DIR && docker compose restart"
echo ""
echo "  NOTE: First startup takes ~30s to initialize."
echo "        If the UI doesn't load immediately, wait and retry."
echo "================================================"
