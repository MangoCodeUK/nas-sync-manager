---
name: ship
description: Deploy NAS Sync Manager to the TerraMaster NAS and prove the new image is really running. Use for "ship it", "deploy", "push to the NAS", "update the NAS", "why can't I see my change", or whenever a change has to be running on the NAS before the user can look at it. Also use on its own to report which commit the NAS is currently running.
---

# Ship NAS Sync Manager to the NAS

Shipping is **push to `main` -> GitHub Actions builds images -> the NAS pulls
them**. Nothing reaches the NAS until that last step, so a green CI run is not a
deploy and a commit is not a deploy. Run this end to end.

`deploy/manage.ps1` does the same loop interactively for the user. It needs a
human at the keyboard, so drive SSH directly from here instead - the NAS accepts
key auth, so every command below is non-interactive.

## Connection

Read it, never guess it. `deploy/nas.env` is gitignored and machine-local:

```sh
cd "D:/AI/Projects/Claude/NAS Sync"
NAS_USER=$(grep '^NAS_USER=' deploy/nas.env | cut -d= -f2-)
NAS_HOST=$(grep '^NAS_HOST=' deploy/nas.env | cut -d= -f2-)
NAS_PORT=$(grep '^NAS_PORT=' deploy/nas.env | cut -d= -f2-)
NAS_DIR=$(grep  '^NAS_DIR='  deploy/nas.env | cut -d= -f2-)
SSH="ssh -p $NAS_PORT -o BatchMode=yes $NAS_USER@$NAS_HOST"
```

`NAS_DIR` contains spaces, so quote it in every remote command: `cd "$NAS_DIR"`.

Pipe SSH output through `grep -v "post-quantum\|store now\|openssh.com"` - the
server prints a three-line PQ key-exchange warning on every single connection
that otherwise buries the real output.

If `deploy/nas.env` is missing or its `NAS_DIR` is wrong, recover it from the
running container rather than guessing (see **Traps**).

## The loop

**1. Test.** Both must pass before anything is pushed.

```sh
cd backend  && ./.venv/Scripts/python.exe -m pytest -q
cd frontend && npm run build          # tsc --noEmit && vite build
```

**2. Commit and push to `main`.** CI only builds `main`; a branch produces no
image, so a feature branch has to land before it can ship.

**3. Wait for the image.** Do not deploy a run that has not finished - the NAS
would pull the previous `latest` and look like the deploy silently did nothing.

```sh
gh run list --limit 1
gh run watch <id> --exit-status --interval 10
```

**4. Deploy.** Send both compose files, then pull and recreate. The share list
goes first because it is the file that gets edited.

```sh
cat docker-compose.shares.yml | $SSH "cd \"$NAS_DIR\" && cat > docker-compose.shares.yml"

cat docker-compose.prod.yml | $SSH "cd \"$NAS_DIR\" \
  && cat > docker-compose.prod.yml \
  && export PATH=\$(ls -d /Volume*/@apps/DockerEngine/dockerd/bin 2>/dev/null | head -1):\$PATH \
  && { docker compose version >/dev/null 2>&1 && DC='docker compose' || DC='docker-compose'; } \
  && \$DC pull && \$DC up -d && \$DC ps"
```

**Never add `-f` flags.** Which files make up the stack comes from
`COMPOSE_FILE` in the NAS's `.env`. Naming the files on the command line
overrides it and drops every share bind mount - the stack still comes up healthy
and every rsync job then fails with "not bind-mounted into the container". That
is what happened on 2026-09-01.

**5. Verify - not optional.** "The containers started" is not evidence the new
code is running. Compare the image label against local `HEAD`:

```sh
git rev-parse HEAD
$SSH 'export PATH=$(ls -d /Volume*/@apps/DockerEngine/dockerd/bin 2>/dev/null | head -1):$PATH
  for c in nas-sync-backend nas-sync-frontend; do
    echo -n "$c: "; docker inspect $c --format "{{index .Config.Labels \"org.opencontainers.image.revision\"}}"
  done
  docker inspect nas-sync-backend --format "{{range .Mounts}}{{.Destination}}{{println}}{{end}}" | grep /nas/'
```

Both revisions must equal the commit that was pushed and built, and the
`/nas/...` mounts must be listed. If a revision is behind, the pull did not take
- check `IMAGE_TAG=latest` in the NAS `.env`. (A docs- or skill-only commit made
afterwards moves `HEAD` past the deployed image with nothing actually wrong;
compare against the commit CI built, not blindly against `HEAD`.)

**6. Tell the user to hard-refresh (Ctrl+Shift+R).** nginx serves `index.html`
with no cache headers and the JS bundle is content-hashed, so a browser sitting
on the old page keeps the old bundle indefinitely. Clicking around inside the
SPA never reloads it.

## Traps

**"I deployed but nothing changed."** Work out which half is stale before
touching anything. Backend-rendered content (API responses, error text, plan
reasons) proves the backend; layout and labels prove the frontend bundle. If
backend-rendered content is old, the deploy did not take - check the revision
label. If only the layout is old, it is the browser cache.

**`cd: /Volume1/...: No such file or directory`.** The app folder is **not**
under `/Volume1` - it is `/home/<user>/AI Applications/NAS Sync`. `bash`
answering at all means SSH, the port and auth are all fine; only the path is
wrong. Recover the real path from the container rather than hunting for it:

```sh
$SSH 'export PATH=$(ls -d /Volume*/@apps/DockerEngine/dockerd/bin 2>/dev/null | head -1):$PATH
  docker inspect nas-sync-backend --format "{{index .Config.Labels \"com.docker.compose.project.working_dir\"}}"'
```

Then write it back into `deploy/nas.env` so the next deploy - and
`manage.ps1` - both get it right.

**The NAS has other stacks on it** (`broker-*`, `public-caddy`, `local-dns`).
Scope every docker command to the `nas-sync-*` containers or to `$NAS_DIR`;
never run `docker compose down`, a bare `docker prune`, or anything else that
reaches across projects.
