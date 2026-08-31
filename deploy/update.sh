#!/bin/sh
# Pull latest images + restart (run on the NAS).  sh deploy/update.sh
set -e
cd "$(CDPATH= cd "$(dirname "$0")/.." && pwd)"

DOCKER_BIN="$(ls -d /Volume*/@apps/DockerEngine/dockerd/bin 2>/dev/null | head -1 || true)"
[ -n "$DOCKER_BIN" ] && PATH="$DOCKER_BIN:$PATH"

if docker compose version >/dev/null 2>&1; then DC="docker compose";
elif command -v docker-compose >/dev/null 2>&1; then DC="docker-compose";
else echo "Docker Compose not found." >&2; exit 1; fi
# A first update from an older install may not have the share list yet; the
# stack runs fine without it (no shares mounted, which the app reports).
if [ ! -f docker-compose.shares.yml ]; then
  cat > docker-compose.shares.yml <<'SHARES'
services:
  backend:
    volumes: []
SHARES
fi

# Two files: the stack, and the share list that is meant to be edited.
DC="$DC -f docker-compose.prod.yml -f docker-compose.shares.yml"

$DC pull
$DC up -d
$DC ps

cid=$($DC ps -q backend 2>/dev/null | head -n1)
if [ -n "$cid" ]; then
  rev=$(docker inspect "$cid" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' 2>/dev/null || true)
  echo ""
  echo "Backend now running commit: ${rev:-unknown}  (hard-refresh the browser: Ctrl+Shift+R)"
fi
