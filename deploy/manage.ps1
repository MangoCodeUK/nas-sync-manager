# NAS Sync Manager - deploy menu (Windows PowerShell).
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File .\deploy\manage.ps1
# Pure ASCII on purpose: Windows PowerShell 5.1 mojibakes non-ASCII and breaks parsing.

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$NasEnv   = Join-Path $PSScriptRoot "nas.env"
$ComposeFile = "docker-compose.prod.yml"
$SharesFile  = "docker-compose.shares.yml"

function Read-NasEnv {
    $cfg = @{}
    if (Test-Path $NasEnv) {
        foreach ($line in Get-Content $NasEnv) {
            if ($line -match '^\s*([A-Z_]+)\s*=\s*(.*)$') { $cfg[$Matches[1]] = $Matches[2].Trim() }
        }
    }
    return $cfg
}

function Save-NasEnv($cfg) {
    $lines = $cfg.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }
    Set-Content -Path $NasEnv -Value $lines -Encoding ASCII
}

function Ensure-NasConfig {
    $cfg = Read-NasEnv
    if (-not $cfg.NAS_HOST) { $cfg.NAS_HOST = Read-Host "NAS host/IP" }
    if (-not $cfg.NAS_USER) { $cfg.NAS_USER = Read-Host "NAS SSH user (e.g. MangoUK)" }
    if (-not $cfg.NAS_PORT) {
        $p = Read-Host "NAS SSH port (TerraMaster is often 9222) [9222]"
        $cfg.NAS_PORT = if ([string]::IsNullOrWhiteSpace($p)) { "9222" } else { $p }
    }
    if (-not $cfg.NAS_DIR)  { $cfg.NAS_DIR = Read-Host "App folder on the NAS (e.g. /Volume1/AI Applications/NAS Sync)" }
    Save-NasEnv $cfg
    return $cfg
}

function Get-Branch { (git -C $RepoRoot rev-parse --abbrev-ref HEAD).Trim() }

function Run-Tests {
    Write-Host "== Backend tests ==" -ForegroundColor Cyan
    $py = Join-Path $RepoRoot "backend\.venv\Scripts\python.exe"
    if (-not (Test-Path $py)) { $py = "python" }
    Push-Location (Join-Path $RepoRoot "backend")
    try { & $py -m pytest; if ($LASTEXITCODE -ne 0) { throw "Backend tests failed." } }
    finally { Pop-Location }

    Write-Host "== Frontend build ==" -ForegroundColor Cyan
    Push-Location (Join-Path $RepoRoot "frontend")
    try { npm run build; if ($LASTEXITCODE -ne 0) { throw "Frontend build failed." } }
    finally { Pop-Location }
    Write-Host "All green." -ForegroundColor Green
}

function Invoke-Commit {
    git -C $RepoRoot add -A
    $status = git -C $RepoRoot status --short
    if (-not $status) { Write-Host "Nothing to commit." -ForegroundColor Yellow; return $false }
    Write-Host $status
    $msg = Read-Host "Commit message"
    if ([string]::IsNullOrWhiteSpace($msg)) { Write-Host "Empty message, aborting commit." -ForegroundColor Yellow; return $false }
    git -C $RepoRoot commit -m $msg
    return $true
}

function Push-ToMain {
    $branch = Get-Branch
    if ($branch -ne "main") {
        Write-Host "Landing '$branch' on main (fast-forward)..." -ForegroundColor Cyan
        git -C $RepoRoot checkout main
        git -C $RepoRoot merge --ff-only $branch
        if ($LASTEXITCODE -ne 0) { git -C $RepoRoot checkout $branch; throw "Cannot fast-forward main from '$branch'. Resolve manually." }
    }
    git -C $RepoRoot push origin main
    if ($LASTEXITCODE -ne 0) { throw "git push failed." }
    if ($branch -ne "main") { git -C $RepoRoot checkout $branch }
}

function Wait-CI {
    if (Get-Command gh -ErrorAction SilentlyContinue) {
        $id = gh run list --repo (Get-RepoSlug) --branch main --workflow "Publish Docker images" --limit 1 --json databaseId -q ".[0].databaseId" 2>$null
        if ($id) {
            Write-Host "Watching CI run $id ..." -ForegroundColor Cyan
            gh run watch $id --exit-status --repo (Get-RepoSlug)
            if ($LASTEXITCODE -ne 0) { throw "CI build failed - not deploying." }
            return
        }
    }
    Read-Host "Wait for the green GHCR build on GitHub, then press Enter to continue"
}

function Get-RepoSlug {
    $url = git -C $RepoRoot remote get-url origin 2>$null
    if ($url -match '[:/]([^/]+/[^/]+?)(\.git)?$') { return $Matches[1] }
    return $null
}

function Update-Nas {
    $cfg = Ensure-NasConfig
    $target = "$($cfg.NAS_USER)@$($cfg.NAS_HOST)"
    $port = $cfg.NAS_PORT
    $dir = $cfg.NAS_DIR
    $composePath = Join-Path $RepoRoot $ComposeFile

    # Single SSH connection: write compose from stdin, then pull + up + ps.
    # Single-quote the remote dir (space-safe). No double quotes in the remote
    # command (PowerShell would strip them before ssh.exe sees them).
    $dockerPath = 'export PATH=$(ls -d /Volume*/@apps/DockerEngine/dockerd/bin 2>/dev/null | head -1):$PATH'
    $pickDC = '{ docker compose version >/dev/null 2>&1 && DC=''docker compose'' || DC=''docker-compose''; }'
    $files = '-f docker-compose.prod.yml -f docker-compose.shares.yml'
    $run = "`$DC $files pull && `$DC $files up -d && `$DC $files ps"
    $cmd = 'cd ''' + $dir + ''' && cat > docker-compose.prod.yml && ' + $dockerPath + ' && ' + $pickDC + ' && ' + $run

    Write-Host "Deploying to ${target}:$dir ..." -ForegroundColor Cyan
    # Send the share list first (it is the file people edit), then the stack.
    Get-Content -Raw (Join-Path $RepoRoot $SharesFile) |
        ssh -p $port $target ("cd '" + $dir + "' && cat > docker-compose.shares.yml")
    if ($LASTEXITCODE -ne 0) { throw 'Could not copy the share list to the NAS.' }
    Get-Content -Raw $composePath | ssh -p $port $target $cmd
    if ($LASTEXITCODE -ne 0) { throw "NAS update failed." }
    Write-Host "Deployed. Open http://$($cfg.NAS_HOST):<WEB_PORT> and hard-refresh (Ctrl+Shift+R)." -ForegroundColor Green
}

function Show-Status {
    Write-Host "== Git ==" -ForegroundColor Cyan
    git -C $RepoRoot status --short --branch
    Write-Host "`n== Last CI build ==" -ForegroundColor Cyan
    if (Get-Command gh -ErrorAction SilentlyContinue) {
        gh run list --repo (Get-RepoSlug) --branch main --workflow "Publish Docker images" --limit 3 2>$null
    } else { Write-Host "(gh not installed)" }
    Write-Host "`n== NAS containers ==" -ForegroundColor Cyan
    $cfg = Read-NasEnv
    if ($cfg.NAS_HOST) {
        $dockerPath = 'export PATH=$(ls -d /Volume*/@apps/DockerEngine/dockerd/bin 2>/dev/null | head -1):$PATH'
        $cmd = $dockerPath + ' && cd ''' + $cfg.NAS_DIR + ''' && { docker compose version >/dev/null 2>&1 && DC=''docker compose'' || DC=''docker-compose''; } && $DC -f docker-compose.prod.yml -f docker-compose.shares.yml ps'
        ssh -p $cfg.NAS_PORT "$($cfg.NAS_USER)@$($cfg.NAS_HOST)" $cmd
    } else { Write-Host "(NAS not configured yet)" }
}

function Show-Menu {
    $branch = Get-Branch
    $cfg = Read-NasEnv
    $nas = if ($cfg.NAS_HOST) { "$($cfg.NAS_USER)@$($cfg.NAS_HOST)" } else { "not configured" }
    Write-Host ""
    Write-Host "=== Deploy: NAS Sync Manager  (branch: $branch, NAS: $nas) ===" -ForegroundColor White
    Write-Host "  1) Commit, push & update NAS   - full release"
    Write-Host "  2) Commit & push               - build images, leave the NAS"
    Write-Host "  3) Commit only                 - local checkpoint"
    Write-Host "  4) Update NAS now              - redeploy current images"
    Write-Host "  5) Status                      - git, last CI build, NAS containers"
    Write-Host "  6) Run tests                   - backend pytest + frontend build"
    Write-Host "  q) Quit"
}

while ($true) {
    Show-Menu
    $choice = Read-Host "Choose"
    try {
        switch ($choice) {
            "1" { Run-Tests; if (Invoke-Commit) { Push-ToMain; Wait-CI; Update-Nas } }
            "2" { Run-Tests; if (Invoke-Commit) { Push-ToMain } }
            "3" { Invoke-Commit | Out-Null }
            "4" { Wait-CI; Update-Nas }
            "5" { Show-Status }
            "6" { Run-Tests }
            "q" { break }
            "Q" { break }
            default { Write-Host "Unknown option." -ForegroundColor Yellow }
        }
    } catch {
        Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    }
}
