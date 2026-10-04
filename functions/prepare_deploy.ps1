# PowerShell script to bundle backend code into the scheduled function package
# Run this before: func azure functionapp publish (from functions/scheduled_pipeline)
# $Files must match the backend modules reachable from scheduled_pipeline/function_app.py

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$SourceRoot = Join-Path $RepoRoot "backend"
$TargetRoot = Join-Path $PSScriptRoot "scheduled_pipeline\backend"

$Files = @(
    "daily_publish_to_briefs.py",
    "db/database.py",
    "db/models.py",
    "db/queries.py",
    "ingestion/hn_ingest.py",
    "ingestion/stackexchange_ingest.py",
    "llm/translate.py"
)

if (Test-Path $TargetRoot) {
    Write-Host "Removing previous bundle at functions/scheduled_pipeline/backend..."
    Remove-Item -Recurse -Force $TargetRoot
}

foreach ($File in $Files) {
    $RepoPath = "backend/$File"
    $Name = Split-Path -Leaf $File

    if ($Name -like ".env*" -or $Name -eq "local.settings.json" -or [IO.Path]::GetExtension($Name) -ne ".py") {
        throw "Refusing to copy non-Python or secret-like file: $RepoPath"
    }

    git -C $RepoRoot ls-files --error-unmatch -- $RepoPath | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Not tracked by git, refusing to copy: $RepoPath"
    }

    git -C $RepoRoot check-ignore -q -- $RepoPath
    if ($LASTEXITCODE -eq 0) {
        throw "Ignored by git, refusing to copy: $RepoPath"
    }

    $Destination = Join-Path $TargetRoot $File
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Copy-Item -LiteralPath (Join-Path $SourceRoot $File) -Destination $Destination
    Write-Host "Copied $RepoPath -> functions/scheduled_pipeline/backend/$File"
}

Write-Host "Bundled $($Files.Count) files into functions/scheduled_pipeline/backend."
