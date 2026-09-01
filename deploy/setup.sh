#!/bin/sh
# One-time setup on the NAS: create .env, pull images, start. Run:  sh deploy/setup.sh
set -e
cd "$(CDPATH= cd "$(dirname "$0")/.." && pwd)"

# TerraMaster keeps docker off the non-interactive SSH PATH; add it if present.
DOCKER_BIN="$(ls -d /Volume*/@apps/DockerEngine/dockerd/bin 2>/dev/null | head -1 || true)"
[ -n "$DOCKER_BIN" ] && PATH="$DOCKER_BIN:$PATH"

# Detect v2 plugin vs old v1 binary.
if docker compose version >/dev/null 2>&1; then DC="docker compose";
elif command -v docker-compose >/dev/null 2>&1; then DC="docker-compose";
else echo "Docker Compose not found. Install the Docker app in TOS first." >&2; exit 1; fi

[ -f .env ] || { cp .env.example .env; echo "Created .env from the template. Edit IMAGE_OWNER and WEB_PORT if needed."; }

# Which compose files make up the stack lives in .env, not in this script - see
# the COMPOSE_FILE comment in .env.example. The scripts on the NAS are copies
# that no update refreshes, so a hard-coded file list here would be free to
# drift away from the repo and quietly deploy the wrong stack. Must be settled
# before the first compose command below.
if ! grep -q '^COMPOSE_FILE=' .env 2>/dev/null; then
  echo 'COMPOSE_FILE=docker-compose.prod.yml:docker-compose.shares.yml' >> .env
fi

# shellcheck disable=SC1091
. ./.env 2>/dev/null || true

if [ "${IMAGE_OWNER:-changeme}" = "changeme" ]; then
  printf "GitHub owner (lowercase) for the GHCR images: "
  read OWNER
  if [ -n "$OWNER" ]; then
    grep -v '^IMAGE_OWNER=' .env > .env.tmp 2>/dev/null || true
    echo "IMAGE_OWNER=$OWNER" >> .env.tmp
    mv .env.tmp .env
  fi
fi

echo "Pulling images from ghcr.io ..."
if ! $DC pull; then
  echo "Pull failed - images are probably private. Log in (GitHub username + PAT with read:packages):"
  docker login ghcr.io
  $DC pull
fi

$DC up -d
$DC ps
WEB_PORT="${WEB_PORT:-8088}"
echo ""
echo "Done. Open: http://<nas-ip>:${WEB_PORT}"
