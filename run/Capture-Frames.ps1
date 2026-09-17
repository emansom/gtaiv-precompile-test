#requires -Version 5.1
<#
.SYNOPSIS
  Capture per-frame present times for GTAIV.exe with PresentMon -> CSV, for a
  fixed number of seconds. Run as Administrator (PresentMon uses ETW).

.DESCRIPTION
  GTA IV must already be RUNNING and in gameplay at your route start before you
  call this. Capture begins immediately and runs for -Seconds; drive the FIXED
  route during that window. PresentMon self-terminates and writes the CSV.

.PARAMETER Seconds     Capture duration (default 90). Same value for OFF and ON.
.PARAMETER OutputCsv   Output CSV path.
.PARAMETER ProcessName Target process (default GTAIV.exe).
.PARAMETER PresentMon  Path to PresentMon.exe (default tools\presentmon\PresentMon.exe).
.PARAMETER PresentMon2 Use PresentMon 2.x '--' flag style instead of 1.x '-'.
.EXAMPLE
  .\Capture-Frames.ps1 -Seconds 90 -OutputCsv .\results\raw\off.csv
#>
[CmdletBinding()]
param(
    [int]$Seconds = 90,
    [Parameter(Mandatory=$true)][string]$OutputCsv,
    [string]$ProcessName = 'GTAIV.exe',
    [string]$PresentMon,
    [switch]$PresentMon2
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Common.ps1"

if (-not (Test-IsAdmin)) {
    throw "PresentMon needs Administrator (ETW). Re-launch this shell / Claude Code 'as Administrator' and retry."
}
if (-not $PresentMon) {
    $PresentMon = Join-Path $RepoRoot 'tools\presentmon\PresentMon.exe'
}
if (-not (Test-Path -LiteralPath $PresentMon)) {
    throw "PresentMon.exe not found at $PresentMon -- run tools\presentmon\Get-PresentMon.ps1 first."
}

# Confirm the game is running (PresentMon can only capture a live, presenting process).
$proc = Get-Process -Name ($ProcessName -replace '\.exe$','') -ErrorAction SilentlyContinue
if (-not $proc) {
    Write-Warn2 "$ProcessName is not running yet. Launch GTA IV and reach your route start BEFORE capturing."
}

$outDir = Split-Path -Parent $OutputCsv
if ($outDir) { New-DirIfMissing $outDir }
if (Test-Path -LiteralPath $OutputCsv) { Remove-Item -LiteralPath $OutputCsv -Force }

if ($PresentMon2) {
    $pmArgs = @('--process_name', $ProcessName, '--output_file', $OutputCsv,
              '--timed', "$Seconds", '--terminate_after_timed',
              '--stop_existing_session', '--no_console_stats')
} else {
    # PresentMon 1.x classic flags.
    $pmArgs = @('-process_name', $ProcessName, '-output_file', $OutputCsv,
              '-timed', "$Seconds", '-terminate_after_timed',
              '-stop_existing_session', '-no_top')
}

Write-Step "Capturing $Seconds s of $ProcessName present times -> $OutputCsv"
Write-Host  "    DRIVE THE FIXED ROUTE NOW. Keep GTA IV focused (foreground)." -ForegroundColor Yellow
Write-Host  "    PresentMon: $PresentMon $($pmArgs -join ' ')" -ForegroundColor DarkGray

$sw = [Diagnostics.Stopwatch]::StartNew()
$p = Start-Process -FilePath $PresentMon -ArgumentList $pmArgs -PassThru -Wait -NoNewWindow
$sw.Stop()

if (-not (Test-Path -LiteralPath $OutputCsv)) {
    throw "PresentMon produced no CSV. Was GTA IV presenting? Was the shell elevated? (exit $($p.ExitCode))"
}
$rows = (Get-Content -LiteralPath $OutputCsv | Measure-Object -Line).Lines
if ($rows -lt 5) {
    Write-Warn2 "CSV has only $rows lines -- the game may not have been presenting. Check $OutputCsv."
} else {
    Write-Ok "Captured ~$($rows-1) present samples in $([math]::Round($sw.Elapsed.TotalSeconds,1))s -> $OutputCsv"
}
return $OutputCsv
