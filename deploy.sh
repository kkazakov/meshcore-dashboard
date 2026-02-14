#!/usr/bin/env bash
# deploy.sh — rebuild from source and deploy the Meshcore Dashboard stack
# Usage:
#   ./deploy.sh          # rebuild image + (re)deploy detached
#   ./deploy.sh --logs   # rebuild + deploy, then follow logs
#   ./deploy.sh --down   # stop and remove containers
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.yaml"
PROJECT_NAME="meshcore"

# ── Colours ───────────────────────────────────────────────────────────────────
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
RESET="\033[0m"

info()    { echo -e "${GREEN}[deploy]${RESET} $*"; }
warning() { echo -e "${YELLOW}[deploy]${RESET} $*"; }
error()   { echo -e "${RED}[deploy]${RESET} $*" >&2; }

# ── .env check ────────────────────────────────────────────────────────────────
if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
  warning ".env not found — copying from .env.example"
  cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
  warning "Edit .env with your device and database settings, then re-run."
  exit 1
fi

# ── Handle flags ──────────────────────────────────────────────────────────────
FOLLOW_LOGS=false
BRING_DOWN=false

for arg in "$@"; do
  case "$arg" in
    --logs) FOLLOW_LOGS=true ;;
    --down) BRING_DOWN=true ;;
    *) error "Unknown argument: $arg"; exit 1 ;;
  esac
done

if $BRING_DOWN; then
  info "Stopping and removing containers…"
  docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" down
  info "Done."
  exit 0
fi

# ── Build (always rebuild from source, no layer cache) ────────────────────────
info "Rebuilding image from source…"
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" build --pull --no-cache

# ── Deploy ────────────────────────────────────────────────────────────────────
info "Deploying stack…"
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up -d --force-recreate

# ── Prune dangling images left by the rebuild ─────────────────────────────────
info "Pruning dangling images…"
docker image prune -f --filter "label!=keep" > /dev/null

# ── Status ────────────────────────────────────────────────────────────────────
info "Running containers:"
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" ps

info "API available at  http://localhost:8080"
info "API docs:         http://localhost:8080/docs"

if $FOLLOW_LOGS; then
  info "Following logs (Ctrl+C to stop)…"
  docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" logs -f
fi
