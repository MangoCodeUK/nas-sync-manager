You are continuing development and configuration work on my existing NAS Sync Manager application.

IMPORTANT:
This is an EXISTING application. Do not start a new project, replace the application, or redesign it from scratch.

Before making any code changes:
1. Inspect the existing NAS Sync Manager project/repository.
2. Understand its current architecture, deployment mechanism, Docker configuration, database/schema, FTP implementation, scheduling implementation, credential handling, logging, and UI.
3. Check any existing project documentation/instructions.
4. Check whether you already have the SSH/deployment information for my new TerraMaster NAS from our previous work.
5. Report what you find before making architectural changes.
6. Preserve all existing working functionality.

The objective is to extend NAS Sync Manager so that it supports rsync in addition to its existing FTP functionality.

============================================================
1. ENVIRONMENT
============================================================

I have two TerraMaster NAS devices.

OLD NAS
--------
Capacity: approximately 8 TB
TOS: 4.2.41
Native rsync service: YES
FTP: YES

NEW NAS
--------
Capacity: approximately 14 TB
TOS: 5.1.145
Native rsync service: YES
FTP: YES
Docker support: YES

NAS Sync Manager is already deployed/running on the NEW NAS.

You may already have:
- SSH host/IP
- SSH port
- SSH username
- authentication information/configuration
- Docker deployment information
- application paths
- existing deployment/update scripts

SEARCH YOUR EXISTING PROJECT CONTEXT/FILES FOR THESE FIRST.

Do not ask me to recreate configuration that already exists unless you genuinely cannot recover it.

Never expose passwords, SSH private keys, tokens, or other secrets in logs, source code, screenshots, responses, or Git commits.

============================================================
2. RSYNC TESTING ALREADY COMPLETED
============================================================

Do NOT repeat these tests unless there is a technical reason to do so.

We have successfully tested native rsync between the two TerraMaster devices.

Direction tested:

OLD NAS (8 TB / TOS 4.2.41)
        |
        | rsync
        v
NEW NAS (14 TB / TOS 5.1.145)

The NEW NAS was configured as the rsync destination/server.

A dedicated rsync test destination was created:

    RsyncTest

A test source was created on the OLD NAS:

    RsyncSourceTest

Initial source contents included:

RsyncSourceTest/
├── test1.txt
├── test2.txt
├── FolderA/
└── FolderB/

The TerraMaster rsync backup job successfully copied this to:

RsyncTest/
├── test1.txt
├── test2.txt
├── FolderA/
└── FolderB/

IMPORTANT PATH BEHAVIOUR:

The CONTENTS of RsyncSourceTest were copied into RsyncTest.

It did NOT produce:

RsyncTest/RsyncSourceTest/...

This path/trailing-slash semantic is important and should be explicitly handled by NAS Sync Manager rather than left ambiguous.

============================================================
3. INCREMENTAL RSYNC TEST RESULTS
============================================================

On TOS 4.2.41, the following option was selected:

    "Backup modified files and folders only"

Other options shown by TerraMaster included:

- Activate the encryption
  - uses SSH
  - default SSH port shown as 22
- Compression backup
- Suspend all reading and writing operations during backup
- Backup modified files and folders only
- Backup all
- Sparse file backup

For our test we selected ONLY:

    Backup modified files and folders only

Encryption: OFF
Compression: OFF
Suspend I/O: OFF
Backup all: OFF
Sparse file backup: OFF

TEST 1 - NEW FILE
-----------------
A new file was added to the source.

Result:
It was copied successfully.

TEST 2 - MODIFIED FILE
----------------------
test1.txt was modified.

Result:
The changed version was transferred successfully.

TEST 3 - UNCHANGED FILE
------------------------
test2.txt was left unchanged.

Result:
Normal incremental behaviour occurred.

TEST 4 - SOURCE DELETION
------------------------
test2.txt was deleted from the OLD NAS source.

The rsync job was run again.

Result:

    test2.txt REMAINED on the NEW NAS.

Therefore the TerraMaster option:

    "Backup modified files and folders only"

DOES NOT behave as a true mirror.

It behaves as a non-destructive COPY/UPDATE operation.

TEST 5 - DESTINATION-ONLY FILE
------------------------------
We manually created:

    destination-only.txt

on the NEW NAS destination.

The rsync job was run again.

Result:

    destination-only.txt REMAINED.

Therefore we have experimentally established:

COPY/UPDATE behaviour:

✓ Copy new source files
✓ Update changed source files
✓ Retain files deleted from source
✓ Retain destination-only files

This should be treated as PROVEN behaviour.

============================================================
4. PRODUCT DIRECTION
============================================================

NAS Sync Manager should NOT become:

    "an FTP application with some rsync commands added"

Instead, evolve the existing architecture carefully toward:

    NAS synchronisation/orchestration application
                  |
           Transfer Providers
             /         \
          FTP          rsync
                       |
                  future providers
                  e.g. SFTP/SMB

HOWEVER:

Do not perform a large refactor merely to achieve architectural purity.

Inspect the existing application first.

Make the smallest sensible architectural changes that give us a clean provider abstraction without destabilising the working FTP implementation.

Existing FTP functionality MUST continue to work.

============================================================
5. SEPARATE OPERATION FROM TRANSPORT
============================================================

A fundamental design requirement is that "what the user wants to do" and "how files are transported" are separate concepts.

For example:

OPERATION:
- Copy/Update
- Mirror
- Move
- potentially Backup/Snapshot later

TRANSPORT:
- rsync
- FTP
- potentially SFTP
- potentially SMB later

Do NOT hard-code concepts such as:

    FTP Job
    Rsync Job

if the existing architecture can reasonably support:

    Sync Job
       |
       +-- operation
       +-- transport/provider

For example:

Job:
    Movies Mirror

Source:
    Old NAS:/Movies

Destination:
    New NAS:/Movies

Operation:
    Mirror

Transport:
    rsync

============================================================
6. INITIAL OPERATION DEFINITIONS
============================================================

COPY/UPDATE
-----------

Required behaviour:

- Copy new files
- Update changed files
- Do NOT remove destination-only files
- Do NOT propagate source deletions

This corresponds to the TerraMaster behaviour we have already tested.

This should be the DEFAULT and SAFEST rsync mode.

MIRROR
------

Required behaviour:

Destination should ultimately reflect the source.

This means:

- Copy new files
- Update changed files
- Remove destination files that no longer exist on source

THIS IS DESTRUCTIVE.

Do not implement this as an unsafe raw "--delete" checkbox.

Safety controls are mandatory.

MOVE
----

Conceptually:

1. Transfer source data.
2. Confirm transfer succeeded.
3. Verify according to configured verification policy.
4. Only then remove source data.

Never delete the source merely because an rsync process started or returned partial success.

MOVE must fail safely.

BACKUP/SNAPSHOT
---------------

Potential future feature.

Do not implement unless it naturally falls within the current work.

============================================================
7. RSYNC SAFETY REQUIREMENTS
============================================================

This is extremely important.

NAS Sync Manager must make destructive rsync operations safer than manually running rsync.

For Mirror/Move operations, investigate and design:

DRY RUN
-------

The GUI should support an rsync dry-run/preview.

Before destructive operations, it should be possible to show:

- files to be added
- files to be updated
- files to be deleted
- estimated transfer size where available
- number of changes
- source
- destination

Example:

DRY RUN

12 files will be copied
3 files will be updated
2 files will be deleted

+ MovieA.mkv
+ MovieB.mkv
> MovieC.mkv
- OldMovie.mkv

No actual changes should occur during dry-run.

DELETION THRESHOLD
------------------

Introduce configurable protection such as:

Abort if deletion would affect more than:

    X files

and/or:

    Y% of destination contents

Example defaults can be proposed, but do not silently choose dangerous values.

SOURCE/DESTINATION VALIDATION
-----------------------------

Before running destructive jobs:

- validate both paths
- ensure source and destination have not accidentally been reversed
- prevent obviously dangerous destinations
- prevent root-level accidental deletion where possible
- detect empty/unavailable source scenarios

CRITICAL:

If the source NAS/share becomes unavailable, NAS Sync Manager must NEVER interpret:

    "source appears empty"

as:

    "delete everything from destination"

A disconnected source must cause the job to FAIL SAFE.

============================================================
8. RSYNC EXECUTION ARCHITECTURE
============================================================

We now need to determine the best way for NAS Sync Manager itself to control rsync.

Do not assume that TerraMaster's built-in Backup GUI needs to be automated.

Preferred architecture, if technically feasible:

NAS Sync Manager
    running on NEW NAS / Docker
           |
           +--> invokes/manages rsync itself
           |
           +--> communicates with NAS rsync services and/or SSH
           |
           +--> captures progress/results/logs

We want the application to control:

- source
- destination
- operation
- schedule
- rsync arguments
- dry-run
- exclusions
- logging
- progress
- bandwidth limits
- verification
- deletion protection

FIRST INVESTIGATE:

1. Is rsync installed inside the existing NAS Sync Manager container?

2. If not, is it available on the Docker host?

3. What base image does NAS Sync Manager use?

4. Can rsync safely be added to the container image?

5. Does the application already have SSH capability/libraries?

6. What rsync connection modes are supported by both TerraMaster NAS devices?

7. Should we use:
   - rsync daemon protocol
   - rsync over SSH
   - another supported TerraMaster mechanism

8. Can the existing TerraMaster rsync authentication be used directly?

9. What limitations exist between:
   TOS 4.2.41
   and
   TOS 5.1.145?

10. What happens when NAS Sync Manager needs to PUSH vs PULL?

Because NAS Sync Manager runs on the NEW NAS, consider whether jobs should normally be implemented as:

    NEW NAS pulls from OLD NAS

rather than:

    OLD NAS pushes to NEW NAS

if this provides better control.

Do not assume the direction. Investigate it.

============================================================
9. SSH
============================================================

The previous ChatGPT session asked me to inspect SSH on the NEW NAS.

However, you may already possess the required SSH information from the original NAS Sync Manager deployment.

SEARCH YOUR EXISTING CONTEXT FIRST.

If you already have working SSH details, use them appropriately.

Do not ask me for them again unnecessarily.

Do not make changes to SSH configuration unless required.

Do not expose credentials.

If you genuinely do not have sufficient SSH information, tell me exactly what information is missing.

============================================================
10. CONNECTION MANAGEMENT
============================================================

Longer term, NAS Sync Manager should have a reusable Connection abstraction.

Conceptually:

CONNECTION

Name:
    Old TerraMaster

Host:
    <address>

Capabilities:
    FTP
    rsync
    SSH
    etc.

Individual transport configurations may require:

RSYNC:
- host
- port
- username
- authentication
- module/share
- SSH settings if applicable

FTP:
- existing configuration

The GUI should provide:

    Test Connection

Where practical, capability detection would be useful.

For example:

Old TerraMaster

✓ FTP
✓ rsync
✓ SSH
✗ SFTP

Do not assume all capabilities can be reliably auto-detected. Investigate first.

============================================================
11. CREDENTIAL SECURITY
============================================================

Review the existing application's credential storage.

Passwords/private keys must NOT be:

- stored in plaintext if avoidable
- committed to Git
- displayed in logs
- returned through APIs unnecessarily
- exposed in browser developer responses
- included in generated command previews

If command previews are displayed, credentials must be redacted.

For example:

GOOD:

rsync ... nas-sync@192.168.x.x::module

BAD:

rsync://username:actualpassword@...

If the existing FTP credential handling is weak, identify this as technical debt and propose a migration approach.

Do not silently break existing stored credentials.

============================================================
12. GUI REQUIREMENTS
============================================================

The existing NAS Sync Manager GUI should be extended rather than replaced.

A Sync Job should ultimately expose something similar to:

JOB NAME
    Movies Mirror

SOURCE
    NAS
    path

DESTINATION
    NAS
    path

OPERATION
    Copy/Update
    Mirror
    Move

TRANSPORT
    rsync
    FTP

SCHEDULE
    manual
    scheduled

RSYNC OPTIONS
    preserve timestamps
    preserve permissions where supported
    partial transfers
    compression
    bandwidth limit
    include/exclude rules
    verification/checksum policy
    sparse file handling where appropriate

ADVANCED
    show generated rsync command
    BUT REDACT ALL CREDENTIALS

A "Dry Run" control should be prominent for rsync jobs.

============================================================
13. FILE BROWSER
============================================================

Preserve the original NAS Sync Manager goal of browsing both NAS devices.

Longer-term GUI concept:

OLD NAS                         NEW NAS

Movies                          Movies
Music                           Music
Photos                          Photos
Documents                       Backup

Possible actions:

    COPY ->
    MOVE ->
    <- COPY
    CREATE SYNC JOB

The browsing implementation should ideally be independent of transfer provider where practical.

Do not break the existing FTP browser while implementing rsync.

============================================================
14. LOGGING AND AUDIT
============================================================

Every job run should eventually record:

- job ID
- job name
- start time
- finish time
- source
- destination
- operation
- provider
- result
- number of files transferred
- number updated
- number skipped
- number deleted
- bytes transferred
- errors
- exit code
- dry-run status

Where available, capture rsync's useful statistics.

Do not store secrets in logs.

For destructive operations, log exactly what deletion safety checks were performed.

============================================================
15. SCHEDULING
============================================================

NAS Sync Manager already has/was intended to have scheduling.

Review the existing scheduler before changing anything.

rsync jobs should use the same scheduling framework as FTP jobs wherever sensible.

Do not build an entirely separate rsync scheduler.

Jobs should support at least:

- Manual
- Daily
- configurable schedule

Preserve any richer scheduling capability already implemented.

============================================================
16. ERROR HANDLING
============================================================

The application must distinguish between conditions such as:

- source unavailable
- destination unavailable
- authentication failure
- permission failure
- insufficient destination storage
- rsync executable unavailable
- network interruption
- partial transfer
- verification failure
- deletion threshold triggered
- user cancellation
- invalid path
- SSH host-key issue if applicable

A failed job must fail safely.

Particularly:

NEVER DELETE SOURCE DATA AFTER A FAILED/PARTIAL MOVE.

NEVER MASS-DELETE DESTINATION DATA BECAUSE SOURCE BECAME UNAVAILABLE.

============================================================
17. PROGRESS REPORTING
============================================================

Investigate rsync's available machine-readable/progress output.

The GUI should ideally be able to show:

    Running

    327 / 1,204 files

    73.4 GB / 220 GB

    33%

    112 MB/s

    ETA 21m

Do not fake progress values if rsync cannot provide a particular metric reliably.

============================================================
18. PERFORMANCE
============================================================

Both NAS devices are likely less powerful than a modern desktop PC.

Do not blindly enable:

- compression
- full checksums
- expensive verification

for every job.

For large media files on a local LAN, compression may provide little benefit while increasing CPU usage.

Expose sensible configuration choices.

We should eventually be able to compare:

FTP performance
vs
rsync performance

using the application.

============================================================
19. DO NOT IMPLEMENT TRUE TWO-WAY SYNC YET
============================================================

Do NOT currently implement:

    NAS A <--> NAS B

as automatic bidirectional rsync.

Rsync is fundamentally directional and conflict handling becomes a separate problem.

For now:

    Source -> Destination

Jobs are explicitly directional.

If proper bidirectional sync is wanted later, investigate appropriate technology separately.

============================================================
20. DEVELOPMENT APPROACH
============================================================

This application manages real NAS data, so development must be conservative.

Rules:

1. Inspect before modifying.
2. Preserve working functionality.
3. Make small, testable changes.
4. Do not perform destructive tests against real folders.
5. Use dedicated test directories.
6. Dry-run wherever possible.
7. Never guess about paths.
8. Never guess about credentials.
9. Never silently change existing deployment configuration.
10. Never expose secrets.
11. Comment non-obvious code clearly.
12. Keep code maintainable by both humans and future AI developers.
13. Update documentation as architecture changes.
14. Keep installation/deployment/update mechanisms working.
15. Do not commit secrets or generated credential files.

============================================================
21. TEST ENVIRONMENT
============================================================

Continue using:

OLD NAS:
    RsyncSourceTest

NEW NAS:
    RsyncTest

for development/testing wherever possible.

These contain disposable test data.

DO NOT use Movies, Photos, Documents, backups, or other real data for destructive testing.

Before any destructive rsync test, tell me exactly what is about to happen.

============================================================
22. FIRST TASK - DO THIS NOW
============================================================

Do NOT begin by coding the entire rsync GUI.

Start with discovery.

PHASE 1 - EXISTING APPLICATION AUDIT

Inspect the existing NAS Sync Manager project and report:

A. Current application architecture

B. Language/framework

C. Docker configuration

D. Existing FTP implementation

E. Existing connection model

F. Existing job model

G. Existing scheduler

H. Existing database/schema

I. Existing credential storage

J. Existing logging

K. Existing deployment/update scripts

L. Existing tests

M. Existing SSH/deployment information you already possess

PHASE 2 - RSYNC ENVIRONMENT DISCOVERY

Determine:

A. Whether rsync exists inside the application container.

B. Its version.

C. Whether the container can reach both NAS devices.

D. Whether rsync daemon port 873 is reachable where required.

E. Whether SSH is available where required.

F. Which rsync architecture is best:
   - daemon
   - SSH
   - push
   - pull

G. Whether additional Docker packages/configuration are required.

Do not make destructive changes during discovery.

PHASE 3 - PROPOSE INTEGRATION PLAN

Based on actual findings, propose:

- minimal architecture changes
- provider abstraction
- database changes/migrations
- API changes
- GUI changes
- credential changes
- rsync execution service
- progress parsing
- logging changes
- safety mechanisms
- test strategy
- deployment changes

Categorise proposed work as:

MUST
SHOULD
COULD
FUTURE

PHASE 4 - STOP FOR REVIEW

After the audit and integration plan, STOP.

Do not implement the full feature until I have reviewed the findings.

You may make harmless diagnostic checks during discovery, but do not modify production NAS data.

============================================================
23. IMPORTANT CONTEXT FROM CHATGPT HANDOVER
============================================================

The previous ChatGPT session concluded that adding rsync is both feasible and desirable.

However, architectural suggestions in this handover are recommendations, NOT evidence about how the existing code is actually structured.

The experimentally verified facts are specifically the TerraMaster rsync test results described above.

Where this prompt says:

    "investigate"
    "consider"
    "preferred"
    "should ideally"

you must validate against the actual application/environment.

Do not convert assumptions into facts.

The goal is to evolve the existing working NAS Sync Manager safely into a multi-provider NAS synchronisation manager.

Begin with PHASE 1 now.