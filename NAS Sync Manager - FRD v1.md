Below is a Claude-ready FRD in Markdown format. I’ve included **questions for you** inside a dedicated section, but I’ve also made sensible assumptions so Claude can start building without waiting.

---

# Functional Requirements Document

# TerraMaster NAS Folder Mirror & Move Manager

**Project Name:** NAS Sync Manager
**Target User:** Single administrator / home-lab owner
**Primary Environment:** TerraMaster NAS devices, newer NAS running Docker
**Transfer Method:** FTP / FTPS
**Primary Interface:** Web application hosted on the newer NAS
**Build Target:** Claude Code / AI coding assistant
**Version:** 1.0 Draft
**Date:** 25 June 2026

---

## 1. Project Summary

The user has two TerraMaster NAS devices. The newer NAS supports Docker and will host a web-based file management and scheduled synchronisation application.

The application must allow the user to connect to both NAS devices over FTP or FTPS, browse both folder structures side by side, and define transfer jobs between them.

There are two primary use cases:

1. **Mirror folders**
   Keep selected folders on the newer NAS updated from the older NAS on a schedule.

2. **Move folders**
   Safely transfer selected folders from the old NAS to the new NAS, then optionally delete or archive the originals after verification.

The system must provide a simple web interface, persistent job configuration, scheduled execution, logs, dry-run preview, safety checks, and a single installation/deployment script that can install locally, deploy to the NAS, commit changes to GitHub, and apply updates.

---

## 2. Core Design Decision

FTP or FTPS will be the default transfer mechanism because FTP is already installed on both TerraMaster devices.

The system must support:

* FTP
* FTPS where available
* Passive mode
* Configurable ports
* Username/password authentication
* Connection testing
* Folder browsing
* Recursive folder transfer
* File comparison
* Scheduled synchronisation
* Transfer logs
* Error reporting
* Safe move workflow

SFTP may be added later, but it is not required for version 1 unless the user confirms SSH is enabled on both NAS devices.

---

## 3. High-Level Architecture

The application should run as a Docker container on the newer TerraMaster NAS.

Recommended stack:

* **Backend:** Python FastAPI
* **Frontend:** HTML, CSS, JavaScript, or lightweight React/Vite if Claude prefers
* **Database:** SQLite
* **Scheduler:** APScheduler or equivalent
* **Transfer Engine:** Python FTP/FTPS library
* **Deployment:** Docker Compose
* **Single Management Script:** PowerShell script for Windows host

The application should expose a local web interface, for example:

```text
http://<new-nas-ip>:8088
```

The app should not require external cloud services.

---

## 4. Primary User Goals

The user needs to:

* See the folder structure of the old NAS.
* See the folder structure of the new NAS.
* Select folders from either side.
* Define whether selected folders should be copied, mirrored, or moved.
* Schedule those operations.
* Review what will happen before execution.
* See job history, errors, skipped files, copied files, deleted files, and warnings.
* Avoid accidental deletion.
* Install, deploy, update, and maintain the application using a single script.

---

## 5. User Roles

### 5.1 Administrator

The initial version only requires one user role: Administrator.

The administrator can:

* Configure NAS connections.
* Browse folders.
* Create sync jobs.
* Edit jobs.
* Disable jobs.
* Run jobs manually.
* Run dry-runs.
* View logs.
* Approve deletion after a move.
* Manage application settings.
* Trigger backups of the app configuration.

Authentication should be included even for a single-user deployment.

Minimum requirement:

* Local admin login
* Username and password
* Password stored securely as a hash
* Session-based login

Optional later enhancement:

* TOTP MFA

---

## 6. NAS Connection Requirements

### FR-001: Add NAS Connection

The system must allow the user to define NAS connection profiles.

Each profile must include:

* Display name
* Hostname or IP address
* Protocol: FTP or FTPS
* Port
* Username
* Password
* Passive mode enabled/disabled
* Root path
* Connection timeout
* Description/notes

Example profiles:

```text
Old TerraMaster NAS
New TerraMaster NAS
```

---

### FR-002: Test Connection

The system must provide a **Test Connection** button for each NAS profile.

The test must verify:

* Network connectivity
* Authentication
* Ability to list the configured root directory
* Whether write access is available
* Whether delete access is available

The result should be clearly displayed in the UI.

---

### FR-003: Secure Credential Storage

FTP credentials must not be stored in plain text where avoidable.

Preferred approach:

* Store encrypted credentials in SQLite.
* Use an application secret generated during first install.
* Store the secret in a Docker volume or `.env` file.
* Do not commit secrets to GitHub.

---

## 7. Folder Browser Requirements

### FR-004: Dual-Pane Folder Browser

The web interface must show both NAS folder structures side by side.

Suggested layout:

```text
+----------------------------+----------------------------+
| Old NAS                    | New NAS                    |
| /                          | /                          |
| ├── Photos                 | ├── Photos                 |
| ├── Media                  | ├── Media                  |
| ├── Backups                | ├── Migrated               |
| └── Documents              | └── Documents              |
+----------------------------+----------------------------+
```

The user must be able to:

* Expand folders.
* Collapse folders.
* Refresh a folder.
* Select a source folder.
* Select a destination folder.
* View folder path.
* See basic metadata where available.

---

### FR-005: Folder Metadata

When a folder is selected, the app should show:

* Full path
* NAS profile
* Number of child folders, if quick to retrieve
* Number of files, if quick to retrieve
* Estimated size, if supported or calculated
* Last scanned time

Large folder size calculation must be optional because recursive FTP scans can be slow.

---

### FR-006: File Preview

The user should be able to open a selected folder and see files inside.

The file list should display:

* File name
* Type
* Size
* Modified date
* Path
* Transfer status if part of a job

---

## 8. Transfer Job Types

The system must support three job types.

---

### 8.1 Copy Job

A copy job copies files from source to destination.

Behaviour:

* New files are copied.
* Existing files are skipped unless overwrite rules say otherwise.
* Source files remain untouched.
* Destination files not present in the source remain untouched.

Use case:

```text
Copy selected folders from old NAS to new NAS without removing anything.
```

---

### 8.2 Mirror Job

A mirror job keeps the destination aligned with the source.

Behaviour:

* New files are copied.
* Changed files are updated.
* Unchanged files are skipped.
* Optional: destination files not present in source are deleted or moved to archive.

Deletion must be disabled by default.

Mirror modes:

```text
Mirror Safe Mode:
- Copy new files.
- Update changed files.
- Do not delete destination-only files.

Mirror Strict Mode:
- Copy new files.
- Update changed files.
- Delete or archive destination-only files.
```

Strict mode must require explicit confirmation.

---

### 8.3 Move Job

A move job migrates folders from source to destination.

Move must never be implemented as a simple immediate delete.

The required workflow is:

1. Copy source files to destination.
2. Verify copied files.
3. Mark source files as ready for deletion.
4. Require approval, unless the user has enabled automatic deletion.
5. Delete source files only after verification.
6. Log all deleted files.

Supported move deletion modes:

```text
Manual Approval:
- Copy and verify.
- User manually approves source deletion.

Auto Delete After Verification:
- Copy and verify.
- Delete source automatically only if verification passes.

Archive Instead of Delete:
- Copy and verify.
- Move original source into an archive folder on the old NAS, if supported.

Never Delete:
- Copy and verify.
- Mark job complete but leave source untouched.
```

Default must be:

```text
Manual Approval
```

---

## 9. File Comparison and Verification

### FR-007: Comparison Strategy

The system must determine whether files need copying.

Minimum comparison rules:

* Path exists or does not exist.
* File size differs.
* Modified timestamp differs.

Optional stronger verification:

* Checksum comparison.
* Sample hash.
* Full file hash.

Because FTP does not always expose reliable hashing, the system must support configurable verification levels.

---

### FR-008: Verification Levels

The application must support these verification levels:

#### Level 1: Basic

* Confirm destination file exists.
* Confirm file size matches.

#### Level 2: Timestamp and Size

* Confirm destination file exists.
* Confirm size matches.
* Confirm modified date is within tolerance.

#### Level 3: Checksum Where Available

* Use checksum if the FTP server supports it.
* Fall back to Level 2 if not supported.

#### Level 4: Download and Hash

* Download source and destination streams and compare hashes.
* Slowest but strongest.
* Useful for important move jobs.

Default:

```text
Level 2: Timestamp and Size
```

---

## 10. Scheduling Requirements

### FR-009: Job Scheduling

The user must be able to schedule each job independently.

Supported schedule types:

* Manual only
* Every X minutes
* Hourly
* Daily
* Weekly
* Monthly
* Custom cron expression

Each job must have:

* Enabled/disabled toggle
* Next run time
* Last run time
* Last result
* Manual run button
* Dry-run button

---

### FR-010: Schedule Timezone

The app must use the configured timezone.

Default:

```text
Europe/London
```

The timezone must be configurable.

---

### FR-011: Prevent Overlapping Runs

The same job must not run twice at the same time.

If a job is already running and the scheduler tries to start it again, the new run should be skipped and logged.

---

## 11. Dry-Run and Preview Requirements

### FR-012: Dry-Run

Every job must support a dry-run mode.

Dry-run must show:

* Files that would be copied
* Files that would be overwritten
* Files that would be skipped
* Files that would be deleted
* Files that would be archived
* Estimated total transfer size
* Warnings
* Permission issues

No file changes must occur during dry-run.

---

### FR-013: Job Preview Before Save

When creating or editing a job, the user should be able to run a preview before saving.

The preview should identify obvious risks, for example:

* Destination folder is empty.
* Destination folder appears to be wrong.
* Source and destination are the same.
* Strict mirror deletion is enabled.
* Move job has auto-delete enabled.
* Destination has files not present in source.

---

## 12. Safety Requirements

### FR-014: Deletion Protection

Deletion must be protected.

The app must require explicit confirmation for:

* Strict mirror deletion
* Move source deletion
* Bulk deletion
* Deleting more than a configurable number of files
* Deleting more than a configurable amount of data

Default safety limits:

```text
Max automatic source deletes per job: 0
Max automatic destination deletes per job: 0
Require manual approval for all deletes: true
```

---

### FR-015: Quarantine / Archive Option

Instead of deleting files, the app should support moving files into a configured archive folder.

Example:

```text
/_NAS_SYNC_ARCHIVE/<job-name>/<date-time>/
```

This is preferred for the first version of risky operations.

---

### FR-016: Conflict Handling

The user must be able to choose what happens when files differ.

Options:

* Skip existing file
* Overwrite if source is newer
* Overwrite if size differs
* Always overwrite
* Rename destination copy
* Keep both

Default:

```text
Overwrite if source is newer or size differs
```

---

### FR-017: Partial Transfer Protection

The app must avoid leaving corrupted destination files.

Required behaviour:

* Transfer to temporary filename first.
* Verify temporary file.
* Rename temporary file to final filename only after successful transfer.

Example temporary filename:

```text
example.mp4.__nas_sync_tmp
```

---

## 13. Web Interface Requirements

### FR-018: Dashboard

The dashboard must show:

* NAS connection status
* Total number of jobs
* Enabled jobs
* Running jobs
* Failed jobs
* Last successful run
* Next scheduled run
* Recent activity

---

### FR-019: Connections Page

The connections page must allow the user to:

* Add NAS connection
* Edit NAS connection
* Delete NAS connection
* Test connection
* Set default source NAS
* Set default destination NAS

---

### FR-020: Browse Page

The browse page must show the two NAS devices side by side.

The user must be able to:

* Browse source folders
* Browse destination folders
* Select source and destination
* Create a job from selection
* Manually copy selected folder
* Manually move selected folder
* Refresh folders

---

### FR-021: Jobs Page

The jobs page must show all configured jobs.

Each job row should show:

* Job name
* Job type
* Source path
* Destination path
* Schedule
* Enabled status
* Last run
* Last result
* Next run
* Actions

Actions:

* Run now
* Dry-run
* Edit
* Disable
* View logs
* Delete job

---

### FR-022: Job Editor

The job editor must support:

* Job name
* Job description
* Source NAS
* Source path
* Destination NAS
* Destination path
* Job type: copy, mirror, move
* Schedule
* Conflict handling
* Verification level
* Delete/archive behaviour
* Include filters
* Exclude filters
* Enabled toggle

---

### FR-023: Logs Page

The logs page must show:

* Job run history
* Status
* Start time
* End time
* Duration
* Files scanned
* Files copied
* Files skipped
* Files failed
* Files deleted
* Data transferred
* Error messages

The user must be able to filter logs by:

* Job
* Status
* Date range
* Error only
* Dry-run only

---

### FR-024: Settings Page

The settings page must allow configuration of:

* Timezone
* Default verification level
* Default transfer mode
* Max concurrent transfers
* Max bandwidth, optional
* Log retention
* Archive folder naming
* App admin password
* Backup/export settings
* Restore/import settings

---

## 14. Filtering Requirements

### FR-025: Include and Exclude Rules

Each job must support include and exclude filters.

Examples:

```text
Exclude:
*.tmp
*.part
@Recycle/
#recycle/
Thumbs.db
.DS_Store
```

Supported rule types:

* File extension
* Filename pattern
* Folder name
* Full path contains
* Regex, optional advanced mode

---

## 15. Transfer Engine Requirements

### FR-026: Recursive Transfer

The transfer engine must recursively process folders and files.

It must:

* Create missing destination folders.
* Transfer files.
* Preserve folder structure.
* Handle nested folders.
* Retry failed transfers.
* Log all actions.

---

### FR-027: Resume / Retry

The app should support retrying failed transfers.

Minimum requirement:

* Failed files are logged.
* User can rerun the job.
* Already transferred files are skipped if they pass verification.

Optional enhancement:

* Resume partial FTP transfers if supported.

---

### FR-028: Bandwidth and Concurrency

The user should be able to configure:

* Maximum concurrent transfers
* Optional bandwidth limit
* Retry count
* Retry delay

Default:

```text
Concurrent transfers: 2
Retry count: 3
Retry delay: 30 seconds
```

---

## 16. Database Requirements

The system must persist configuration in SQLite.

Suggested tables:

```text
users
nas_connections
sync_jobs
job_schedules
job_runs
job_run_items
app_settings
audit_log
pending_deletions
```

---

### 16.1 nas_connections

Fields:

```text
id
name
host
protocol
port
username
encrypted_password
root_path
passive_mode
timeout_seconds
created_at
updated_at
last_test_status
last_test_at
```

---

### 16.2 sync_jobs

Fields:

```text
id
name
description
job_type
source_connection_id
source_path
destination_connection_id
destination_path
enabled
conflict_strategy
verification_level
delete_strategy
archive_path
schedule_type
schedule_value
created_at
updated_at
last_run_at
next_run_at
last_status
```

---

### 16.3 job_runs

Fields:

```text
id
job_id
run_type
status
started_at
completed_at
duration_seconds
files_scanned
files_copied
files_updated
files_skipped
files_failed
files_deleted
bytes_transferred
summary
error_message
```

---

### 16.4 job_run_items

Fields:

```text
id
job_run_id
source_path
destination_path
action
status
size_bytes
message
created_at
```

---

### 16.5 pending_deletions

Fields:

```text
id
job_id
job_run_id
source_path
destination_path
size_bytes
verification_status
approved
approved_at
deleted
deleted_at
created_at
```

---

## 17. API Requirements

The backend should expose a clean API for the frontend.

Suggested endpoints:

```text
POST   /api/auth/login
POST   /api/auth/logout
GET    /api/auth/me

GET    /api/connections
POST   /api/connections
GET    /api/connections/{id}
PUT    /api/connections/{id}
DELETE /api/connections/{id}
POST   /api/connections/{id}/test

GET    /api/browse/{connection_id}
GET    /api/browse/{connection_id}?path=/example

GET    /api/jobs
POST   /api/jobs
GET    /api/jobs/{id}
PUT    /api/jobs/{id}
DELETE /api/jobs/{id}

POST   /api/jobs/{id}/run
POST   /api/jobs/{id}/dry-run
POST   /api/jobs/{id}/enable
POST   /api/jobs/{id}/disable

GET    /api/jobs/{id}/runs
GET    /api/runs/{run_id}
GET    /api/runs/{run_id}/items

GET    /api/pending-deletions
POST   /api/pending-deletions/{id}/approve
POST   /api/pending-deletions/{id}/reject

GET    /api/settings
PUT    /api/settings

POST   /api/backup/export
POST   /api/backup/import
```

---

## 18. Installation and Deployment Requirements

The project must include a single management script.

Because the user works from Windows, the primary script should be:

```text
manage-nas-sync.ps1
```

This script must support:

```powershell
.\manage-nas-sync.ps1 install-local
.\manage-nas-sync.ps1 run-local
.\manage-nas-sync.ps1 build
.\manage-nas-sync.ps1 deploy-nas
.\manage-nas-sync.ps1 update-nas
.\manage-nas-sync.ps1 backup
.\manage-nas-sync.ps1 restore
.\manage-nas-sync.ps1 git-init
.\manage-nas-sync.ps1 git-commit
.\manage-nas-sync.ps1 git-push
.\manage-nas-sync.ps1 status
```

---

### 18.1 Local Install

The script must:

* Check for Python.
* Check for Node.js, if frontend build requires it.
* Check for Docker Desktop.
* Create `.env` if missing.
* Create app secret if missing.
* Install backend dependencies.
* Install frontend dependencies.
* Initialise SQLite database.
* Start local development server.

---

### 18.2 Local Run

The script must start the local version.

Expected local URLs:

```text
Backend: http://127.0.0.1:8088
Frontend: http://127.0.0.1:8088
```

Or separate frontend/backend ports if Claude chooses that architecture.

---

### 18.3 Docker Build

The script must:

* Build Docker image.
* Validate Docker Compose file.
* Confirm container starts successfully.
* Display URL after startup.

---

### 18.4 NAS Deployment

The script must support deployment to the new NAS.

Preferred deployment method:

* SSH into the new NAS.
* Create application directory.
* Copy Docker Compose file.
* Copy `.env` template.
* Pull or load Docker image.
* Start container.

However, this needs one confirmation from you:

**Question 1:** Is SSH enabled on the newer TerraMaster NAS?

If SSH is not enabled, Claude should implement an alternative deployment mode:

* Build Docker image locally.
* Export image as `.tar`.
* Provide manual upload instructions for TerraMaster Docker UI.
* Use FTP only for configuration backup/upload if appropriate.

---

### 18.5 GitHub Support

The script must support GitHub workflows.

Commands:

```powershell
.\manage-nas-sync.ps1 git-init
.\manage-nas-sync.ps1 git-commit -Message "Initial build"
.\manage-nas-sync.ps1 git-push
```

The script must:

* Create `.gitignore`.
* Prevent `.env`, credentials, logs, and database files from being committed.
* Allow the user to configure GitHub remote.
* Commit source changes.
* Push to GitHub.

---

### 18.6 Update NAS

The script must support updating the NAS deployment.

Update flow:

1. Pull latest source from GitHub.
2. Build new Docker image.
3. Stop existing NAS container.
4. Backup SQLite database and `.env`.
5. Deploy new image.
6. Start container.
7. Run database migrations.
8. Check health endpoint.
9. Roll back if startup fails.

---

## 19. Docker Requirements

The app must include:

```text
Dockerfile
docker-compose.yml
.env.example
```

Docker Compose should define:

```yaml
services:
  nas-sync-manager:
    build: .
    container_name: nas-sync-manager
    ports:
      - "8088:8088"
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./config:/app/config
    environment:
      - TZ=Europe/London
    restart: unless-stopped
```

The app must store persistent data outside the container.

Persistent folders:

```text
/config
/data
/logs
/backups
```

---

## 20. Backup and Restore Requirements

### FR-029: Configuration Backup

The app must support backup of:

* SQLite database
* App settings
* Job definitions
* NAS connection definitions, excluding or encrypting passwords
* Logs, optional

The management script must support:

```powershell
.\manage-nas-sync.ps1 backup
```

---

### FR-030: Restore

The app must support restoring from backup.

The management script must support:

```powershell
.\manage-nas-sync.ps1 restore -BackupPath "path-to-backup.zip"
```

Restore must stop the running app before replacing database/config files.

---

## 21. Audit and Logging Requirements

### FR-031: Audit Log

The app must record administrative actions.

Examples:

* User login
* Connection added
* Connection edited
* Job created
* Job edited
* Job run manually
* Job scheduled
* Delete approved
* Delete rejected
* Settings changed

---

### FR-032: Transfer Log

Every job run must produce a detailed transfer log.

The log must identify:

* Source path
* Destination path
* Action taken
* Result
* Error message if failed
* Bytes transferred
* Timestamp

---

## 22. Error Handling Requirements

The app must handle:

* FTP connection failure
* Login failure
* Permission denied
* Missing folder
* Destination unavailable
* File locked
* Network drop
* Transfer timeout
* Insufficient storage
* Invalid schedule
* Failed verification
* Delete failure
* Partial transfer cleanup failure

Errors must be visible in the web UI and logs.

---

## 23. Health Check Requirements

The app must expose:

```text
GET /health
```

The health check should return:

```json
{
  "status": "ok",
  "version": "1.0.0",
  "database": "ok",
  "scheduler": "running"
}
```

The management script must use this endpoint after local start and NAS deployment.

---

## 24. Recommended Project Structure

Claude may adjust this if needed, but the recommended structure is:

```text
nas-sync-manager/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── auth/
│   │   ├── api/
│   │   ├── db/
│   │   ├── models/
│   │   ├── services/
│   │   │   ├── ftp_client.py
│   │   │   ├── transfer_engine.py
│   │   │   ├── scheduler.py
│   │   │   ├── verifier.py
│   │   │   └── safety.py
│   │   └── settings.py
│   ├── requirements.txt
│   └── tests/
├── frontend/
│   ├── index.html
│   ├── src/
│   └── package.json
├── docker/
├── data/
├── logs/
├── config/
├── backups/
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore
├── manage-nas-sync.ps1
└── README.md
```

---

## 25. Non-Functional Requirements

### NFR-001: Usability

The app should be understandable to a technical home user without requiring command-line knowledge after installation.

---

### NFR-002: Safety

The app must prioritise data safety over speed.

Deletion should be difficult to enable accidentally.

---

### NFR-003: Performance

The app should handle large folders, but scanning may take time over FTP.

The UI must show progress during long-running operations.

---

### NFR-004: Reliability

Scheduled jobs must survive container restarts.

The app must persist job state and history.

---

### NFR-005: Maintainability

The code must be modular.

Transfer logic, scheduling logic, database logic, and UI logic must be separated.

---

### NFR-006: Offline / Local-Only

The app must run entirely locally.

No cloud service is required.

---

## 26. MVP Scope

The first usable version should include:

* Admin login
* Add/edit/test two NAS FTP connections
* Dual-pane folder browser
* Create copy job
* Create mirror-safe job
* Create move job with manual delete approval
* Dry-run
* Manual run
* Daily/hourly/custom schedule
* Logs
* Docker deployment
* Single PowerShell management script
* GitHub commit/push support

---

## 27. Version 2 Enhancements

Possible later features:

* SFTP support
* SMB support
* Email notifications
* Discord/Telegram notifications
* Storage usage dashboard
* File search
* Duplicate file detection
* Media-specific views
* Checksum cache
* Drag-and-drop job builder
* Multi-user roles
* MFA
* Dark mode
* Mobile responsive interface
* Transfer speed graphs
* Global pause/resume
* NAS free-space monitoring
* Snapshot integration if TerraMaster supports it

---

## 28. Questions for Matthew

Claude should proceed with the assumptions above, but these questions should be answered before finalising the build.

### Q1. Is SSH enabled on the newer TerraMaster NAS?

This matters for automated deployment. Without SSH, the deployment script may need to build a Docker image locally and give you a manual upload step.

Answer: Yes

---

### Q2. Do both NAS devices support FTPS, or only plain FTP?

Answer: Both NAS Devices supportFTP and FTPS.

---

### Q3. Should “move” jobs delete the source automatically after verification, or always wait for your approval?

Answer: Always wait for manual approval.

---

### Q4. Should mirror jobs ever delete files from the destination?

Answer: No. Use safe mirror mode first.

---

### Q5. What are the main folder categories?

Examples:

Photos
Films
TV Shows
Documents
Backups
Music
Software
Projects
Private

This helps Claude create sensible sample jobs and UI labels.

---

### Q6. Do you want the app to send notifications when jobs complete or fail?

Answer: None for version 1

---

### Q7. Should the app preserve file timestamps on the destination NAS?

Answer: Yes, where FTP server support allows it.

---

### Q8. How cautious should the app be with deletes?

Recommended setting for first build:

Never auto-delete.
Create pending deletion list.
Require manual approval in the web UI.

---

## 29. Claude Build Instructions

Claude should build this project incrementally.

### Stage 1: Project Skeleton

Create:

* FastAPI backend
* Basic frontend
* SQLite database
* Dockerfile
* Docker Compose
* PowerShell management script
* Health endpoint

Acceptance criteria:

* App runs locally.
* App runs in Docker.
* `/health` returns OK.

---

### Stage 2: Authentication and Settings

Create:

* Admin user setup
* Login page
* Session/token handling
* Settings page
* Password hashing

Acceptance criteria:

* User can log in.
* User can change app settings.
* Protected pages require login.

---

### Stage 3: NAS Connections

Create:

* Add connection page
* Edit connection page
* Test connection
* FTP/FTPS client service
* Secure credential handling

Acceptance criteria:

* User can add old NAS and new NAS.
* User can test both connections.
* App can list root folders.

---

### Stage 4: Dual-Pane Browser

Create:

* Left NAS browser
* Right NAS browser
* Folder expand/collapse
* File listing
* Create job from selected paths

Acceptance criteria:

* User can browse both NAS devices.
* User can select source and destination folders.

---

### Stage 5: Job Creation and Dry-Run

Create:

* Job model
* Job editor
* Copy job
* Mirror-safe job
* Move job
* Dry-run preview

Acceptance criteria:

* User can create jobs.
* Dry-run shows expected actions.
* Dry-run changes nothing.

---

### Stage 6: Transfer Engine

Create:

* Recursive copy
* Temp file transfer
* Verification
* Retry logic
* Conflict handling
* Logging

Acceptance criteria:

* User can manually run a copy job.
* Files appear at destination.
* Logs show copied/skipped/failed files.

---

### Stage 7: Scheduler

Create:

* Scheduled job runner
* Hourly/daily/weekly/custom cron options
* Job status display
* Prevent overlapping runs

Acceptance criteria:

* Jobs run on schedule.
* Last and next run times are shown.
* Failed jobs are logged.

---

### Stage 8: Move Safety and Pending Deletions

Create:

* Copy-verify-delete workflow
* Pending deletion list
* Manual approval screen
* Archive option if possible

Acceptance criteria:

* Move job copies and verifies files.
* Source files are not deleted without approval.
* User can approve or reject deletion.

---

### Stage 9: Deployment Script

Complete:

```text
manage-nas-sync.ps1
```

Required commands:

```powershell
install-local
run-local
build
deploy-nas
update-nas
backup
restore
git-init
git-commit
git-push
status
```

Acceptance criteria:

* User can install locally with one script.
* User can build Docker image.
* User can deploy/update NAS, subject to SSH/manual deployment mode.
* GitHub workflow is supported safely.

---

## 30. Acceptance Criteria Summary

The project is acceptable when:

* The app runs in Docker on the newer TerraMaster NAS.
* The web UI is accessible from the local network.
* The user can configure both NAS devices using FTP/FTPS.
* The user can browse both folder structures side by side.
* The user can define copy, mirror, and move jobs.
* Jobs can run manually and on a schedule.
* Dry-run previews are available.
* Move jobs verify copied data before deletion.
* Deletes require manual approval by default.
* All jobs are logged.
* The app has a backup and restore process.
* A single PowerShell script manages local install, build, deployment, GitHub commit/push, backup, restore, and updates.

---

## 31. Final Instruction to Claude

Build this as a safe local-first NAS synchronisation manager.

Prioritise:

1. Data safety
2. Clear UI
3. Reliable FTP transfers
4. Dry-run and verification
5. Docker deployment
6. Maintainable code

Do not implement automatic deletion as the default. All destructive actions must be opt-in, visible, logged, and reversible where possible.
