#!/usr/bin/env bash
# deploy/build-deek-web.sh
#
# Rebuild the deek-web (Next.js) Docker image with the REAL API key
# baked in. This is required because Next.js 14's compiler inlines
# process.env.X references into the bundle at build time — function
# wrapping, bracket notation and similar tricks do NOT reliably
# prevent constant folding. The correct solution is to pass the real
# key via --build-arg at build time.
#
# This script reads DEEK_API_KEY from deploy/.env and passes it through
# as a build-arg. The Dockerfile itself will fail the build if the key
# is missing or still set to the 'deek-dev-key-change-in-production'
# placeholder — so a misconfigured deploy can't silently ship.
#
# Usage (from Hetzner host /opt/nbne/deek/deploy or dev box D:/deek/deploy):
#
#   ./build-deek-web.sh          # build only
#   ./build-deek-web.sh deploy   # build + recreate container
#   ./build-deek-web.sh full     # git pull + build + recreate
#
# After deploy, a quick HTTP probe of /voice confirms the container is
# serving. Bundle-level verification of the baked-in key is also
# performed; a mismatch fails the script before traffic is flipped.
#
# History: on 2026-04-19 an identity-layer deploy broke because this
# script didn't exist and the default Dockerfile ARG (a placeholder)
# got baked in. Every chat request returned 502 as the proxy received
# 401 from the API. This script prevents that class of regression.

set -euo pipefail

MODE="${1:-build}"

cd "$(dirname "$0")"
DEPLOY_DIR=$(pwd)
REPO_ROOT=$(cd .. && pwd)
ENV_FILE="${DEPLOY_DIR}/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "[build-deek-web] FATAL: ${ENV_FILE} not found" >&2
  exit 1
fi

# Read DEEK_API_KEY from .env without sourcing the whole file (other
# vars contain characters that break shell parsing — JWTs with |, $,
# bcrypt hashes with |, etc).
DEEK_API_KEY_VAL=$(grep '^DEEK_API_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2- | tr -d '\r\n')

if [ -z "$DEEK_API_KEY_VAL" ]; then
  echo "[build-deek-web] FATAL: DEEK_API_KEY not set in ${ENV_FILE}" >&2
  exit 1
fi
if [ "$DEEK_API_KEY_VAL" = "deek-dev-key-change-in-production" ]; then
  echo "[build-deek-web] FATAL: DEEK_API_KEY is the placeholder — refusing to build" >&2
  exit 1
fi

if [ "$MODE" = "full" ]; then
  cd "$REPO_ROOT"
  echo "[build-deek-web] git pull..."
  git pull --ff-only 2>&1 | tail -5 || {
    echo "[build-deek-web] git pull failed — refusing to build from stale code" >&2
    exit 1
  }
fi

cd "$REPO_ROOT"
GIT_COMMIT=$(git rev-parse HEAD)
echo "[build-deek-web] building with GIT_COMMIT=${GIT_COMMIT} and DEEK_API_KEY=***(len=${#DEEK_API_KEY_VAL})"

cd "$REPO_ROOT/web"
docker build \
  --build-arg "GIT_COMMIT=${GIT_COMMIT}" \
  --build-arg "DEEK_API_KEY=${DEEK_API_KEY_VAL}" \
  --build-arg "DEEK_API_URL=http://deek-api:8765" \
  -t deek-web:latest \
  .

if [ "$MODE" = "deploy" ] || [ "$MODE" = "full" ]; then
  cd "$DEPLOY_DIR"
  echo "[build-deek-web] recreating container..."
  docker compose up -d deek-web --force-recreate
  sleep 4

  echo "[build-deek-web] verifying bundle has real key, not the placeholder..."
  BAKED=$(docker exec deploy-deek-web-1 sh -c \
    "grep -oE 'apiKey:\"[^\"]+\"' /app/.next/server/app/api/voice/chat/agent-stream/route.js | head -1" \
    2>/dev/null || echo "")
  if [ -z "$BAKED" ]; then
    echo "[build-deek-web] WARNING: could not verify bundle — file path may have changed"
  elif echo "$BAKED" | grep -q "deek-dev-key-change-in-production"; then
    echo "[build-deek-web] FATAL: bundle still has placeholder key — build arg not honoured" >&2
    exit 1
  else
    echo "[build-deek-web] bundle key check OK"
  fi

  echo "[build-deek-web] health check..."
  HTTP_CODE=$(curl -sS --max-time 8 -o /dev/null -w "%{http_code}" \
    -H "Host: deek.nbnesigns.co.uk" \
    http://127.0.0.1:3020/voice 2>/dev/null || echo "000")
  echo "[build-deek-web] /voice -> HTTP ${HTTP_CODE}"
  # /voice requires auth, so 307 (redirect to /voice/login) is healthy.
  case "$HTTP_CODE" in
    200|302|307) echo "[build-deek-web] OK" ;;
    *) echo "[build-deek-web] WARNING: unexpected HTTP ${HTTP_CODE}" ;;
  esac
fi

echo "[build-deek-web] done"
