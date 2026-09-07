<#
.SYNOPSIS
  Register (or remove) the daily design-review Windows scheduled task (uses schtasks.exe).

.DESCRIPTION
  Creates a task that runs scripts\daily_review.ps1 every day at a given time, as the
  current user with limited rights (/RL LIMITED, runs only when logged on) so Claude
  Code's login credentials are available.

  NOTE: ASCII-only on purpose (PowerShell 5.1 misparses non-ASCII .ps1 without a BOM).

.PARAMETER Time     Daily trigger time (HH:mm, default 09:00, matching existing reviews/).
.PARAMETER Model    Model passed to daily_review.ps1 (default claude-opus-4-8; claude-sonnet-5 is cheaper).
.PARAMETER RepoDir  Project root (avoid spaces, else /TR needs extra quoting).
.PARAMETER Remove   Remove the scheduled task (uninstall).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_daily_review.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_daily_review.ps1 -Time 08:30 -Model claude-sonnet-5
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_daily_review.ps1 -Remove
#>
param(
    [string]$Time = "09:00",
    [string]$Model = "claude-opus-4-8",
    [string]$RepoDir = "E:\hi\webgl-qa-agent",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$taskName = "WebGL-QA-DailyReview"

if ($Remove) {
    schtasks /Delete /TN $taskName /F
    if ($LASTEXITCODE -eq 0) { Write-Output "Removed scheduled task: $taskName" }
    else { Write-Output "Delete failed or task not present (exit $LASTEXITCODE): $taskName" }
    return
}

$script = Join-Path $RepoDir "scripts\daily_review.ps1"
if (-not (Test-Path $script)) { throw "Wrapper script not found: $script" }
if ($RepoDir -match '\s') { Write-Warning "RepoDir contains whitespace; schtasks /TR may need extra quoting: $RepoDir" }

# All paths in /TR are space-free -> no nested quotes needed.
$tr = "powershell -NoProfile -ExecutionPolicy Bypass -File $script -Model $Model -RepoDir $RepoDir"

schtasks /Create /TN $taskName /TR $tr /SC DAILY /ST $Time /RL LIMITED /F
if ($LASTEXITCODE -ne 0) { throw "schtasks create failed (exit $LASTEXITCODE)" }

Write-Output ""
Write-Output "Registered scheduled task: $taskName (daily $Time, model=$Model)"
Write-Output "Test now:   schtasks /Run /TN $taskName"
Write-Output "Inspect:    schtasks /Query /TN $taskName /V /FO LIST"
Write-Output "Uninstall:  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_daily_review.ps1 -Remove"
