# NAS Sync Manager

A safe, local-first web app for mirroring and moving folders between two
TerraMaster NAS devices over **FTP/FTPS**. Browse both devices side by side,
define **Copy / Mirror / Move** jobs, run them on a schedule, preview with
dry-runs, and keep every destructive action behind verification and manual
approval.

Built to the spec in **`NAS Sync Manager - FRD v1.md`**. Single-user, LAN-only,
runs as Docker containers on the newer NAS.

## Architecture

| Part      | Tech                                                            |
|-----------|----------------------------------------------------------------|
| Backend   | Python 3.12 / FastAPI / Uvicorn, SQLite (SQLAlchemy + Alembic), APScheduler, `ftplib` (FTP/FTPS), Fernet-encrypted credentials |
| Frontend  | React + Vite + TypeScript SPA, served by nginx (proxies `/api` + `/health`) |
| Delivery  | GitHub Actions builds images to GHCR; the NAS pulls them. autoheal sidecar, healthchecks, `restart: unless-stopped` |

```
backend/   FastAPI app, services, tests
frontend/  React SPA + nginx
deploy/     manage.ps1 / manage.sh (dev menu), setup.sh / update.sh (NAS)
docker-compose.prod.yml   what the NAS runs (prebuilt images)
docker-compose.yml        local build fallback
```

## Local development (no Docker required)

Two terminals:

```powershell
# Backend (http://127.0.0.1:8000, /health)
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

```powershell
# Frontend (http://127.0.0.1:5173, proxies /api + /health to :8000)
cd frontend
npm install
npm run dev
```

Run the checks:

```powershell
cd backend;  .\.venv\Scripts\python.exe -m pytest
cd frontend; npm run build
```

## Local run with Docker (when Docker Desktop is installed)

```powershell
docker compose up -d --build      # serves the UI on http://localhost:8088
```

## Deploying to the NAS

See **`DEPLOY.md`**. Short version: `powershell -ExecutionPolicy Bypass -File
.\deploy\manage.ps1` and pick **1) Commit, push & update NAS**.

## Build status (incremental, per the FRD's stages)

- [x] Stage 0 - Scaffold & deploy plumbing (`/health`, compose, CI, deploy menu)
- [x] Stage 1 - Backend core + Settings (SQLAlchemy/Alembic, Fernet creds, Settings page)
- [x] Stage 2 - NAS connections (FTP/FTPS client, Test Connection, Connections page)
- [x] Stage 3 - Dual-pane browser (lazy expand, file listing, opt-in folder size)
- [x] Stage 4 - Jobs + dry-run (CRUD, editor, planner, preview that changes nothing)
- [x] Stage 5 - Transfer engine (temp->verify->rename, retry, verification L1-4)
- [x] Stage 6 - Scheduler (APScheduler, interval/cron, overlap guard)
- [x] Stage 7 - Move safety + pending deletions (copy->verify->approve->delete)
- [x] Stage 8 - Backup/restore, Logs, Dashboard, docs

All nine build stages are complete. Backend: 50 pytest passing (incl. real FTP
transfers via pyftpdlib). Frontend: builds clean.

## Safety model

LAN-only (never port-forward) · FTP passwords encrypted at rest · deletes default
to **0 / manual approval required** · dry-run changes nothing · move = copy ->
verify -> approve -> delete.
