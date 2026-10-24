<#
.SYNOPSIS
  Run the Data Mesh Control Plane locally (SQLite) or deploy it as a Databricks App (Lakebase).

.EXAMPLE
  ./deploy.ps1                                  # local, SQLite, http://localhost:8000
  ./deploy.ps1 -Target local -Reseed            # local with a fresh SQLite database
  ./deploy.ps1 -Target databricks -CliProfile DEFAULT -AppName data-mesh-control-plane
#>
param(
    [ValidateSet("local", "databricks")] [string]$Target = "local",
    [string]$AppName = "data-mesh-control-plane",
    [string]$CliProfile = "",
    [int]$Port = 8000,
    [switch]$Reseed
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if ($Target -eq "local") {
    if (-not (Test-Path ".venv")) { python -m venv .venv }
    $py = Join-Path ".venv" "Scripts/python.exe"
    if (-not (Test-Path $py)) { $py = Join-Path ".venv" "bin/python" }
    & $py -m pip install --disable-pip-version-check -q -r requirements.txt
    if ($LASTEXITCODE) { throw "pip install failed" }

    $env:DB_BACKEND = "sqlite"
    $env:SQLITE_PATH = Join-Path $PSScriptRoot "data/mesh.db"
    $env:HOST = "127.0.0.1"
    $env:PORT = "$Port"
    if ($Reseed -and (Test-Path $env:SQLITE_PATH)) { Remove-Item "$($env:SQLITE_PATH)*" }

    Write-Host "Starting on http://localhost:$Port (SQLite: $($env:SQLITE_PATH))" -ForegroundColor Green
    & $py app.py
    exit $LASTEXITCODE
}

# ---------------------------------------------------------------- Databricks Apps
if (-not (Get-Command databricks -ErrorAction SilentlyContinue)) { throw "Databricks CLI not found: https://docs.databricks.com/dev-tools/cli/install.html" }
$p = @(); if ($CliProfile) { $p = @("--profile", $CliProfile) }

$user = (databricks current-user me -o json @p | ConvertFrom-Json).userName
if (-not $user) { throw "Not authenticated. Run: databricks auth login --host <workspace-url>" }
$src = "/Workspace/Users/$user/apps/$AppName"

databricks apps get $AppName @p *> $null
if ($LASTEXITCODE) {
    Write-Host "Creating app $AppName ..."
    databricks apps create $AppName @p
    if ($LASTEXITCODE) { throw "App creation failed" }
}

Write-Host "Syncing source to $src ..."
databricks sync . $src --full @p
if ($LASTEXITCODE) { throw "Sync failed" }

Write-Host "Deploying ..."
databricks apps deploy $AppName --source-code-path $src @p
if ($LASTEXITCODE) { throw "Deploy failed" }

databricks apps get $AppName -o json @p | ConvertFrom-Json | Select-Object name, url, @{n = "status"; e = { $_.app_status.state } }
Write-Host "Ensure a Lakebase database resource with key 'postgres' is attached to the app (see app.yaml)." -ForegroundColor Yellow
