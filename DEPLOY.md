# Deploying NAS Sync Manager to the TerraMaster NAS

> **LAN-only.** Never port-forward this app to the internet. It holds FTP
> credentials for both NAS devices. For remote access use the NAS's built-in VPN.

## How delivery works

The NAS runs **prebuilt images** pulled from GitHub Container Registry (GHCR).
GitHub Actions builds `nas-sync-manager-backend` and `nas-sync-manager-frontend`
on every push to `main`. The NAS never builds code — it only needs two files in the
app folder: `.env` (set once) and `docker-compose.prod.yml`.

A change ships as: **push to `main` -> CI builds images -> NAS pulls them.** The
dev-side menu (`deploy/manage.ps1`) does the whole loop for you.

## One-time prerequisites on the NAS

1. Install the **Docker** ("Container Manager") app from the TOS App Center.
2. Enable **SSH** in Control Panel (TerraMaster SSH is commonly on port **9222**).
3. Create the app folder, e.g. `/Volume1/<share>/NAS Sync`, and copy this repo's
   `docker-compose.prod.yml`, `.env.example`, and the `deploy/` folder into it
   (the dev menu copies the compose file for you on every deploy).

## First-time setup (on the NAS)

```sh
cd "/Volume1/<share>/NAS Sync"
sh deploy/setup.sh
```

`setup.sh` creates `.env` from the template, prompts for your **GitHub owner**
(for the GHCR image path), pulls the images, and starts the stack. Then open:

```
http://<nas-ip>:8088
```

### Private images note

If the GitHub repo (and therefore the packages) is **private**, the first pull
fails `unauthorized`. `setup.sh` then prompts you to `docker login ghcr.io` with
your GitHub username and a **classic PAT scoped `read:packages`** (stored once in
`~/.docker/config.json`). Alternatively, make the two packages public
(GitHub -> Packages -> package -> settings -> visibility) — the images hold no
secrets; those live in `.env` at runtime.

## Day-to-day: shipping a change (on your Windows PC)

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\manage.ps1
# 1) Commit, push & update NAS  -> tests -> commit -> push main -> wait for green CI -> deploy
```

Option 1 runs tests, commits, lands on `main`, pushes, waits for the green GHCR
build, copies the compose file up, and `pull && up -d` on the NAS over one SSH
connection. Hard-refresh the browser afterwards (Ctrl+Shift+R).

Manual fallback (when SSH'd into the NAS directly):

```sh
sh deploy/update.sh
```

## Changing the web port

Set `WEB_PORT=9090` in the NAS `.env` and re-run `sh deploy/update.sh`.

## Backups

Back up the SQLite data volume (also holds the encryption key) before risky changes:

```sh
docker run --rm -v nassync_data:/data -v "$PWD":/backup alpine \
  tar czf /backup/nassync-data-$(date +%Y%m%d).tar.gz -C /data .
```

Restore by extracting the tarball back into the `nassync_data` volume while the
stack is stopped. (Stage 8 also adds in-app config backup/restore.)
