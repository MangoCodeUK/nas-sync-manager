#!/usr/bin/env bash
# NAS Sync Manager - deploy menu (Git-Bash / Linux).  Run:  sh deploy/manage.sh
# PowerShell users run deploy/manage.ps1 instead.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd "$SCRIPT_DIR/.." && pwd)"
NAS_ENV="$SCRIPT_DIR/nas.env"
# Local repo filenames to push. Named PROD_FILE/SHARES_FILE, not COMPOSE_FILE,
# because COMPOSE_FILE is now compose's own variable on the NAS - see .env.example.
PROD_FILE="docker-compose.prod.yml"
SHARES_FILE="docker-compose.shares.yml"

load_nas_env() { [ -f "$NAS_ENV" ] && . "$NAS_ENV" || true; }

ensure_nas_config() {
    load_nas_env
    [ -n "${NAS_HOST:-}" ] || { printf "NAS host/IP: "; read -r NAS_HOST; }
    [ -n "${NAS_USER:-}" ] || { printf "NAS SSH user (e.g. MangoUK): "; read -r NAS_USER; }
    [ -n "${NAS_PORT:-}" ] || { printf "NAS SSH port [9222]: "; read -r NAS_PORT; NAS_PORT="${NAS_PORT:-9222}"; }
    [ -n "${NAS_DIR:-}" ]  || { printf "App folder on the NAS: "; read -r NAS_DIR; }
    {
        echo "NAS_HOST=$NAS_HOST"
        echo "NAS_USER=$NAS_USER"
        echo "NAS_PORT=$NAS_PORT"
        echo "NAS_DIR=$NAS_DIR"
    } > "$NAS_ENV"
}

branch() { git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD; }
repo_slug() { git -C "$REPO_ROOT" remote get-url origin 2>/dev/null | sed -E 's#.*[:/]([^/]+/[^/]+?)(\.git)?$#\1#'; }

run_tests() {
    echo "== Backend tests =="
    py="$REPO_ROOT/backend/.venv/Scripts/python.exe"
    [ -x "$py" ] || py="python"
    ( cd "$REPO_ROOT/backend" && "$py" -m pytest )
    echo "== Frontend build =="
    ( cd "$REPO_ROOT/frontend" && npm run build )
    echo "All green."
}

invoke_commit() {
    git -C "$REPO_ROOT" add -A
    if [ -z "$(git -C "$REPO_ROOT" status --short)" ]; then echo "Nothing to commit."; return 1; fi
    git -C "$REPO_ROOT" status --short
    printf "Commit message: "; read -r msg
    [ -n "$msg" ] || { echo "Empty message, aborting."; return 1; }
    git -C "$REPO_ROOT" commit -m "$msg"
}

push_to_main() {
    b="$(branch)"
    if [ "$b" != "main" ]; then
        git -C "$REPO_ROOT" checkout main
        git -C "$REPO_ROOT" merge --ff-only "$b"
        git -C "$REPO_ROOT" push origin main
        git -C "$REPO_ROOT" checkout "$b"
    else
        git -C "$REPO_ROOT" push origin main
    fi
}

wait_ci() {
    if command -v gh >/dev/null 2>&1; then
        id="$(gh run list --repo "$(repo_slug)" --branch main --workflow 'Publish Docker images' --limit 1 --json databaseId -q '.[0].databaseId' 2>/dev/null || true)"
        if [ -n "$id" ]; then gh run watch "$id" --exit-status --repo "$(repo_slug)"; return; fi
    fi
    printf "Wait for the green GHCR build, then press Enter..."; read -r _
}

update_nas() {
    ensure_nas_config
    docker_path='export PATH=$(ls -d /Volume*/@apps/DockerEngine/dockerd/bin 2>/dev/null | head -1):$PATH'
    pick_dc='{ docker compose version >/dev/null 2>&1 && DC="docker compose" || DC="docker-compose"; }'
    # No -f flags: the file list comes from COMPOSE_FILE in the NAS's .env, so
    # this command cannot deploy a partial stack even if it is out of date. It
    # used to name only prod.yml, which is what silently dropped every share
    # bind mount on 2026-09-01. Settle the line first in case .env predates it.
    # Braces matter: && and || are left-associative and equal precedence, so an
    # unwrapped "grep || echo" here would swallow everything after it when the
    # grep succeeds, and the deploy would silently never run.
    ensure_list="{ grep -q '^COMPOSE_FILE=' .env 2>/dev/null || echo 'COMPOSE_FILE=docker-compose.prod.yml:docker-compose.shares.yml' >> .env; }"
    run='$DC pull && $DC up -d && $DC ps'
    echo "Deploying to $NAS_USER@$NAS_HOST:$NAS_DIR ..."
    # The share list first (it is the file people edit), then the stack.
    ssh -p "$NAS_PORT" "$NAS_USER@$NAS_HOST" "cd '$NAS_DIR' && cat > $SHARES_FILE" < "$REPO_ROOT/$SHARES_FILE"
    cmd="cd '$NAS_DIR' && cat > $PROD_FILE && $ensure_list && $docker_path && $pick_dc && $run"
    ssh -p "$NAS_PORT" "$NAS_USER@$NAS_HOST" "$cmd" < "$REPO_ROOT/$PROD_FILE"
    echo "Deployed. Hard-refresh the browser (Ctrl+Shift+R)."
}

show_status() {
    echo "== Git =="; git -C "$REPO_ROOT" status --short --branch
    echo; echo "== Last CI build =="
    command -v gh >/dev/null 2>&1 && gh run list --repo "$(repo_slug)" --branch main --workflow 'Publish Docker images' --limit 3 || echo "(gh not installed)"
    echo; echo "== NAS containers =="
    load_nas_env
    if [ -n "${NAS_HOST:-}" ]; then
        docker_path='export PATH=$(ls -d /Volume*/@apps/DockerEngine/dockerd/bin 2>/dev/null | head -1):$PATH'
        ssh -p "$NAS_PORT" "$NAS_USER@$NAS_HOST" "$docker_path && cd '$NAS_DIR' && { docker compose version >/dev/null 2>&1 && DC='docker compose' || DC='docker-compose'; } && \$DC ps"
    else echo "(NAS not configured yet)"; fi
}

while true; do
    b="$(branch)"; load_nas_env
    nas="${NAS_HOST:+$NAS_USER@$NAS_HOST}"; nas="${nas:-not configured}"
    echo
    echo "=== Deploy: NAS Sync Manager  (branch: $b, NAS: $nas) ==="
    echo "  1) Commit, push & update NAS   - full release"
    echo "  2) Commit & push"
    echo "  3) Commit only"
    echo "  4) Update NAS now"
    echo "  5) Status"
    echo "  6) Run tests"
    echo "  q) Quit"
    printf "Choose: "; read -r choice
    case "$choice" in
        1) run_tests; invoke_commit && { push_to_main; wait_ci; update_nas; } ;;
        2) run_tests; invoke_commit && push_to_main ;;
        3) invoke_commit || true ;;
        4) wait_ci; update_nas ;;
        5) show_status ;;
        6) run_tests ;;
        q|Q) break ;;
        *) echo "Unknown option." ;;
    esac
done
