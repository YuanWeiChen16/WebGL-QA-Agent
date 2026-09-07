<#
.SYNOPSIS
  Daily design/architecture review — runs .claude/commands/daily-review.md via
  headless Claude Code, producing reviews/<date>_design_recheck.md
  (read-only on code, writes only under reviews/).

.DESCRIPTION
  Invoked daily by Windows Task Scheduler. Resolves the newest installed
  claude.exe, injects today's date, runs unattended with a whitelist of tools
  plus acceptEdits, and merges all output into reviews/.logs/.

  NOTE: This file is intentionally ASCII-only. PowerShell 5.1 misparses non-ASCII
  in .ps1 files that lack a UTF-8 BOM. The (Chinese) review instructions live in
  .claude/commands/daily-review.md and are read at runtime with -Encoding UTF8.

.PARAMETER Model    Model to use (default claude-opus-4-8 = deep review; claude-sonnet-5 is cheaper).
.PARAMETER RepoDir  Project root.
.PARAMETER Force    Re-run even if today's report already exists.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\daily_review.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\daily_review.ps1 -Model claude-sonnet-5
#>
param(
    [string]$Model = "claude-opus-4-8",
    [string]$RepoDir = "E:\hi\webgl-qa-agent",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

# UTF-8 so the (Chinese) prompt read from disk and passed to claude is correct.
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$OutputEncoding = [System.Text.Encoding]::UTF8

$today = (Get-Date).ToString("yyyy-MM-dd")

# --- 1. Resolve newest claude.exe (version folder changes on update) ---
$base = Join-Path $env:LOCALAPPDATA "Claude-3p\claude-code"
if (-not (Test-Path $base)) { throw "Claude Code install dir not found: $base" }

$verDir = Get-ChildItem $base -Directory -ErrorAction SilentlyContinue |
    Where-Object { Test-Path (Join-Path $_.FullName "claude.exe") } |
    Sort-Object {
        $v = $null
        if ([version]::TryParse($_.Name, [ref]$v)) { $v } else { [version]"0.0.0" }
    } |
    Select-Object -Last 1
if (-not $verDir) { throw "No version folder containing claude.exe under $base" }
$claude = Join-Path $verDir.FullName "claude.exe"

# --- 2. Build prompt (read as UTF-8, strip frontmatter, inject date) ---
$cmdFile = Join-Path $RepoDir ".claude\commands\daily-review.md"
if (-not (Test-Path $cmdFile)) { throw "Review prompt not found: $cmdFile" }
$prompt = Get-Content $cmdFile -Raw -Encoding UTF8
$prompt = [regex]::Replace($prompt, '(?s)^\s*---.*?---\s*', '')   # drop YAML frontmatter
$prompt = $prompt -replace '\{\{DATE\}\}', $today

# --- 3. Log dir ---
$logDir = Join-Path $RepoDir "reviews\.logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir "daily_review_$today.log"

# --- 4. Skip if today's report already exists (unless -Force) ---
$report = Join-Path $RepoDir "reviews\${today}_design_recheck.md"
if ((Test-Path $report) -and (-not $Force)) {
    $msg = "[$([DateTime]::Now)] Today's report already exists, skipping: $report"
    $msg | Out-File -FilePath $log -Append -Encoding utf8
    Write-Output $msg
    return
}

"[$([DateTime]::Now)] using $claude (v$($verDir.Name)), model=$Model" | Out-File -FilePath $log -Encoding utf8

# --- 5. Run headless Claude unattended ---
# Native-exe stderr redirection in PS 5.1 gets wrapped as ErrorRecord and can throw
# under Stop; switch to Continue for the call and merge all streams (*>>) into one log.
$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
Push-Location $RepoDir
try {
    & $claude `
        -p $prompt `
        --model $Model `
        --permission-mode acceptEdits `
        --add-dir $RepoDir `
        --output-format text `
        --allowedTools Read Grep Glob Bash PowerShell Write `
        *>> $log
    $code = $LASTEXITCODE
} finally {
    Pop-Location
    $ErrorActionPreference = $prevEAP
}

"[$([DateTime]::Now)] claude finished, exit code=$code" | Out-File -FilePath $log -Append -Encoding utf8
if ($code -ne 0) {
    # Detect the not-logged-in case explicitly (headless CLI has no cached credentials
    # until 'claude /login' is run once interactively as this user).
    $tail = (Get-Content $log -Raw -Encoding UTF8) -replace "`0", ""   # strip UTF-16 NULs if any
    if ($tail -match "Not logged in|/login") {
        $hint = "[$([DateTime]::Now)] FIX: run once interactively: & `"$claude`" /login  (credentials then persist for scheduled runs)"
        $hint | Out-File -FilePath $log -Append -Encoding utf8
        Write-Warning "Daily review failed: Claude CLI not logged in. Run 'claude /login' once. See $log"
    } else {
        Write-Warning "Daily review exited non-zero ($code); see $log"
    }
    exit $code
}
if (Test-Path $report) {
    Write-Output "OK: $report"
} else {
    Write-Warning "claude finished cleanly but expected report not found: $report (see $log)"
}
