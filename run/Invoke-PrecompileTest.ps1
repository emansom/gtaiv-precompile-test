#requires -Version 5.1
<#
.SYNOPSIS
  Orchestrate the full A/B shader-precompile test (or one phase of it) and emit a
  ready-to-post GitHub-issue result comment. Run in an ELEVATED shell (PresentMon
  needs Administrator). Much of the run is manual (you drive the fixed route), so
  the orchestrator pauses at each gate.

.DESCRIPTION
  Phases (run 'all', or one at a time so Claude Code can step through):
    hardware  collect GPU/CPU/OS -> results\raw\hardware.json
    off       precompile OFF, clear shader cache, capture the route -> raw\off.csv
    on        precompile ON, clear shader cache, verify it ran, capture -> raw\on.csv
    analyze   OFF vs ON spike analysis -> raw\verdict.json (+ PASS/FAIL)
    report    build results\result.md (the issue comment) + result.json
    all       every phase in order
  Between OFF and ON you MUST relaunch GTA IV (the precompile toggle applies on
  the next launch). The orchestrator tells you exactly when.

.EXAMPLE
  # one shot (elevated):
  .\Invoke-PrecompileTest.ps1 -Phase all
  # or step by step:
  .\Invoke-PrecompileTest.ps1 -Phase hardware
  .\Invoke-PrecompileTest.ps1 -Phase off
  ... (relaunch game) ...
  .\Invoke-PrecompileTest.ps1 -Phase on
  .\Invoke-PrecompileTest.ps1 -Phase analyze
  .\Invoke-PrecompileTest.ps1 -Phase report
#>
[CmdletBinding()]
param(
    [ValidateSet('all','hardware','off','on','analyze','report')]
    [string]$Phase = 'all',
    [string]$ConfigPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Common.ps1"

$cfg = if ($ConfigPath) { Import-TestConfig -Path $ConfigPath } else { Import-TestConfig }
$game = Resolve-GamePath -Config $cfg
if (-not $game) { throw "Could not resolve GTA IV path. Set GamePath in config\test.config.psd1." }
New-DirIfMissing $RawDir

$seconds  = if ($cfg.RouteSeconds) { [int]$cfg.RouteSeconds } else { 90 }
$asiPath  = $cfg.AsiPath
$toggle   = @{ Mode = $cfg.ToggleMode; ConfigFile = $cfg.ConfigFile; Section = $cfg.ConfigSection; Key = $cfg.ConfigKey; AsiName = $cfg.AsiName }
$pmon     = Join-Path $RepoRoot 'tools\presentmon\PresentMon.exe'

function Confirm-Continue([string]$msg) {
    Write-Host ""
    Read-Host ">> $msg  (press Enter to continue)" | Out-Null
}

function Ensure-PresentMon {
    if (-not (Test-Path -LiteralPath $pmon)) {
        Write-Step "PresentMon missing -- downloading pinned build"
        & (Join-Path $RepoRoot 'tools\presentmon\Get-PresentMon.ps1') | Out-Null
    }
}

function Phase-Hardware {
    Write-Step "Collecting hardware info"
    & "$PSScriptRoot\Get-HardwareInfo.ps1" -Json (Join-Path $RawDir 'hardware.json') | Out-Null
}

function Phase-Capture([string]$state, [string]$outCsv) {
    if (-not (Test-IsAdmin)) { throw "PresentMon needs Administrator. Re-open the shell elevated." }
    Ensure-PresentMon
    Write-Step "Setting precompile $state"
    $dp = @{ GamePath=$game; State=$state; Mode=$toggle.Mode }
    if ($asiPath) { $dp.AsiPath = $asiPath }
    if ($toggle.ConfigFile) { $dp.ConfigFile = $toggle.ConfigFile }
    if ($toggle.Section)    { $dp.Section    = $toggle.Section }
    if ($toggle.Key)        { $dp.Key        = $toggle.Key }
    if ($toggle.AsiName)    { $dp.AsiName    = $toggle.AsiName }
    & "$PSScriptRoot\Deploy-Precompiler.ps1" @dp

    Confirm-Continue "Fully CLOSE GTA IV if open. Then I'll clear the shader cache."
    Write-Step "Clearing GPU driver pipeline cache + any DXVK state cache (cold baseline)"
    & "$PSScriptRoot\Clear-ShaderCache.ps1" -Vendor Auto -GamePath $cfg.GamePath | Out-Null

    Confirm-Continue "Now LAUNCH GTA IV, load your save, and drive to the FIXED route START. Keep the same start + path for OFF and ON."
    if ($state -eq 'On') {
        Write-Step "Verifying the precompiler actually ran"
        & "$PSScriptRoot\Verify-Precompiler.ps1" -GamePath $game -Json (Join-Path $RawDir 'verify.json') | Out-Null
    }
    Confirm-Continue "Ready at the route start? Capture runs for $seconds s -- be set to DRIVE THE ROUTE the instant it starts"
    & "$PSScriptRoot\Capture-Frames.ps1" -Seconds $seconds -OutputCsv $outCsv -PresentMon $pmon | Out-Null
}

function Phase-Analyze {
    $off = Join-Path $RawDir 'off.csv'; $on = Join-Path $RawDir 'on.csv'
    if (-not (Test-Path $off) -or -not (Test-Path $on)) { throw "Need both $off and $on. Run the off + on phases first." }
    Write-Step "Analyzing OFF vs ON"
    # -Logs is [string[]] at Position 0: pass ONE array, not two positional args.
    & "$PSScriptRoot\Analyze-FrameTimes.ps1" @($off, $on) -Json (Join-Path $RawDir 'verdict.json')
    Write-Host "(analyzer exit $LASTEXITCODE : 0=PASS, 1=FAIL)"
}

function Phase-Report {
    Write-Step "Building the shareable result comment"
    $rp = @{
        HardwareJson = (Join-Path $RawDir 'hardware.json')
        VerdictJson  = (Join-Path $RawDir 'verdict.json')
        OutMd        = (Join-Path $ResultsDir 'result.md')
        OutJson      = (Join-Path $ResultsDir 'result.json')
        RouteSeconds = $seconds
    }
    if (Test-Path (Join-Path $RawDir 'verify.json')) { $rp.VerifyJson = (Join-Path $RawDir 'verify.json') }
    if ($cfg.FusionFixBranch) { $rp.FusionFixBranch = $cfg.FusionFixBranch }
    if ($cfg.FusionFixCommit) { $rp.FusionFixCommit = $cfg.FusionFixCommit }
    if ($cfg.Notes) { $rp.Notes = $cfg.Notes }
    & "$PSScriptRoot\New-ResultReport.ps1" @rp
    Write-Host ""
    Write-Host "Next: post results\result.md to the pinned issue (#1). See CLAUDE.md 'Post the result'." -ForegroundColor Cyan
}

switch ($Phase) {
    'hardware' { Phase-Hardware }
    'off'      { Phase-Capture 'Off' (Join-Path $RawDir 'off.csv') }
    'on'       { Phase-Capture 'On'  (Join-Path $RawDir 'on.csv') }
    'analyze'  { Phase-Analyze }
    'report'   { Phase-Report }
    'all' {
        Phase-Hardware
        Phase-Capture 'Off' (Join-Path $RawDir 'off.csv')
        Confirm-Continue "OFF run done. Fully CLOSE GTA IV -- the ON toggle applies on the next launch."
        Phase-Capture 'On'  (Join-Path $RawDir 'on.csv')
        Phase-Analyze
        Phase-Report
    }
}
