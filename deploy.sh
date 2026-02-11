#!/usr/bin/env bash
# deploy.sh — build and start the Meshcore Dashboard stack locally
# Usage:
#   ./deploy.sh          # build + start (detached)
#   ./deploy.sh --logs   # build + start and follow logs
#   ./deploy.sh --down   # stop and remove containers
set -euo pipefail

COMPOSE_FILE="$(dirname "$0")/docker-compose.yaml"
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
if [[ ! -f .env ]]; then
  warning ".env not found — copying from .env.example"
  cp .env.example .env
  warning "Please edit .env with your device and database settings, then re-run."
  exit 1
fi

# ── Handle flags ──────────────────────────────────────────────────────────────
FOLLOW_LOGS=false
BRING_DOWN=false

for arg in "$@"; do
  case "$arg" in
    --logs)  FOLLOW_LOGS=true ;;
    --down)  BRING_DOWN=true ;;
    *)       error "Unknown argument: $arg"; exit 1 ;;
  esac
done

if $BRING_DOWN; then
  info "Stopping and removing containers…"
  docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" down
  info "Done."
  exit 0
fi

# ── Build ─────────────────────────────────────────────────────────────────────
info "Building images…"
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" build --pull

# ── Start ─────────────────────────────────────────────────────────────────────
info "Starting stack…"
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up -d

# ── Status ────────────────────────────────────────────────────────────────────
info "Containers:"
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" ps

API_PORT="${API_PORT:-8000}"
info "API is available at  http://localhost:${API_PORT}"
info "API docs:            http://localhost:${API_PORT}/docs"

if $FOLLOW_LOGS; then
  info "Following logs (Ctrl+C to stop)…"
  docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" logs -f
fi
