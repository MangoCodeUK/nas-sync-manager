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

# Which compose files make up the stack is read from .env (COMPOSE_FILE), not
# named here. This script is a COPY on the NAS that no update ever refreshes,
# so anything it hard-codes can silently drift away from the repo - and on
# 2026-09-01 exactly that happened: a stale copy still passing only
# "-f docker-compose.prod.yml" recreated the containers with no share mounts at
# all. Keeping the file list in .env, which lives only on the NAS and is never
# overwritten, means a stale script cannot get it wrong: it does not carry it.
if ! grep -q '^COMPOSE_FILE=' .env 2>/dev/null; then
  echo 'COMPOSE_FILE=docker-compose.prod.yml:docker-compose.shares.yml' >> .env
  echo "Added COMPOSE_FILE to .env (the stack file list now lives there)."
fi

$DC pull
$DC up -d
$DC ps

# The failure above was invisible precisely because the stack looked fine:
# both containers started and passed their healthchecks with zero shares
# mounted. Nothing is watching the data path, so check it explicitly - if the
# share list asks for bind mounts, the backend must actually have them.
if grep -qE '^[[:space:]]*-[[:space:]]*/.+:/nas/' docker-compose.shares.yml 2>/dev/null; then
  cid=$($DC ps -q backend 2>/dev/null | head -n1)
  mounted=$(docker inspect "$cid" --format '{{range .Mounts}}{{.Destination}}
{{end}}' 2>/dev/null | grep -c '^/nas/' || true)
  if [ "${mounted:-0}" -eq 0 ]; then
    echo "" >&2
    echo "ERROR: docker-compose.shares.yml lists shares, but the backend came up with" >&2
    echo "       NONE of them mounted. Every rsync job will fail with 'not bind-mounted" >&2
    echo "       into the container' until this is fixed." >&2
    echo "" >&2
    echo "       Usually this means COMPOSE_FILE in .env is wrong, or a compose command" >&2
    echo "       was run with an -f flag that left the share list out. Check:" >&2
    echo "         grep COMPOSE_FILE .env" >&2
    echo "       then re-run this script." >&2
    exit 1
  fi
  echo "Shares mounted: $mounted"
fi

cid=$($DC ps -q backend 2>/dev/null | head -n1)
if [ -n "$cid" ]; then
  rev=$(docker inspect "$cid" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' 2>/dev/null || true)
  echo ""
  echo "Backend now running commit: ${rev:-unknown}  (hard-refresh the browser: Ctrl+Shift+R)"
fi
