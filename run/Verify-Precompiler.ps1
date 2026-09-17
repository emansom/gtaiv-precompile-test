#requires -Version 5.1
<#
.SYNOPSIS
  Confirm the FusionFix shader-precompiler ACTUALLY RAN before trusting an ON
  result -- so a "PASS" can't be a false negative caused by the ASI never loading
  (no ASI = no compiles moved to launch = it would look identical to OFF, but for
  the wrong reason).

.DESCRIPTION
  Checks three things:
   1. the precompiler ASI is present in plugins\;
   2. the precompiler's LOG shows it created ~1734 shaders (bounded set) and
      warmed pipelines, with a launch duration;
   3. (visual) the "Building shaders..." loading-screen overlay appeared this
      launch -- confirm with -OverlaySeen or the interactive prompt.

  Expected/RECOMMENDED precompiler log line (ask the ASI authors to emit it):
     ShaderPrecompile: created <N> shaders, <M> pipelines in <T> ms
     FusionFix <version> (<commit>)
  This script also matches looser patterns and reports what it found.

.EXAMPLE
  .\Verify-Precompiler.ps1 -GamePath "D:\...\GTAIV" -OverlaySeen -Json .\results\raw\verify.json
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$GamePath,
    [string[]]$LogPath,
    [int]$ExpectedShaders = 1734,
    [double]$Tolerance = 0.15,     # +/-15% around the expected shader count
    [switch]$OverlaySeen,
    [string]$AsiName = 'GTAIV.EFLC.FusionFix.asi',
    [string]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\Common.ps1"

$plugins = Join-Path $GamePath 'plugins'
$asiPresent = (Test-Path -LiteralPath (Join-Path $plugins $AsiName)) -or
              ((Get-ChildItem -LiteralPath $plugins -Filter '*.asi' -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -notlike '*.off' }).Count -gt 0)

# Candidate log locations.
$candidates = @()
if ($LogPath) { $candidates += $LogPath }
$candidates += @(
    (Join-Path $GamePath 'FusionFix.log'),
    (Join-Path $GamePath 'shaderprecompile.log'),
    (Join-Path $plugins 'FusionFix.log'),
    (Join-Path $plugins 'shaderprecompile.log')
)
$candidates += (Get-ChildItem -LiteralPath $GamePath -Filter '*.log' -ErrorAction SilentlyContinue |
                Select-Object -Expand FullName)
$candidates += (Get-ChildItem -LiteralPath $plugins -Filter '*.log' -ErrorAction SilentlyContinue |
                Select-Object -Expand FullName)
$candidates = $candidates | Where-Object { $_ } | Select-Object -Unique

$logFound = $null; $shaderCount = $null; $pipelineCount = $null; $durationMs = $null
$fusionVersion = $null; $fusionCommit = $null; $matchedLine = $null

foreach ($lf in $candidates) {
    if (-not (Test-Path -LiteralPath $lf)) { continue }
    $text = Get-Content -LiteralPath $lf -Raw -ErrorAction SilentlyContinue
    if (-not $text) { continue }
    if ($text -match 'precompile|Building shaders|shaders? (created|compiled|warmed)') {
        $logFound = $lf
        $m = [regex]::Match($text, 'created\s+(\d+)\s+shaders?(?:,\s*(\d+)\s+pipelines?)?(?:\s+in\s+(\d+)\s*ms)?', 'IgnoreCase')
        if (-not $m.Success) {
            $m = [regex]::Match($text, '(\d+)\s+shaders?\s+(?:created|compiled|precompiled)', 'IgnoreCase')
        }
        if ($m.Success) {
            $matchedLine = $m.Value
            $shaderCount = [int]$m.Groups[1].Value
            if ($m.Groups.Count -gt 2 -and $m.Groups[2].Success) { $pipelineCount = [int]$m.Groups[2].Value }
            if ($m.Groups.Count -gt 3 -and $m.Groups[3].Success) { $durationMs = [int]$m.Groups[3].Value }
        }
        $vm = [regex]::Match($text, 'FusionFix[^\r\n]*?v?(\d+\.\d+[\w.\-]*)(?:\s*\(([0-9a-f]{7,40})\))?', 'IgnoreCase')
        if ($vm.Success) {
            $fusionVersion = $vm.Groups[1].Value
            if ($vm.Groups[2].Success) { $fusionCommit = $vm.Groups[2].Value }
        }
        break
    }
}

$countOk = $false
if ($shaderCount) {
    $lo = $ExpectedShaders * (1 - $Tolerance); $hi = $ExpectedShaders * (1 + $Tolerance)
    $countOk = ($shaderCount -ge $lo -and $shaderCount -le $hi)
}

# Interactive overlay confirmation if not asserted on the command line.
$overlay = [bool]$OverlaySeen
if (-not $OverlaySeen) {
    try {
        $ans = Read-Host "Did the 'Building shaders...' loading overlay appear this launch? (y/N)"
        $overlay = ($ans -match '^(y|yes)$')
    } catch { }
}

# 'verified' = we have positive evidence the precompile ran (log count OR overlay).
$verified = ($countOk) -or ($logFound -and $shaderCount) -or $overlay

$result = [pscustomobject]@{
    asi_present   = $asiPresent
    log_found     = $logFound
    shader_count  = $shaderCount
    pipeline_count = $pipelineCount
    precompile_ms = $durationMs
    fusionfix_version = $fusionVersion
    fusionfix_commit  = $fusionCommit
    matched_line  = $matchedLine
    count_ok      = $countOk
    overlay_seen  = $overlay
    verified      = [bool]$verified
}

Write-Host "ASI present        : $asiPresent"
Write-Host "Precompile log     : $logFound"
Write-Host "Shaders created    : $shaderCount (expected ~$ExpectedShaders; ok=$countOk)"
Write-Host "Pipelines / time   : $pipelineCount / $durationMs ms"
Write-Host "FusionFix version  : $fusionVersion ($fusionCommit)"
Write-Host "Overlay seen       : $overlay"
if ($verified) { Write-Ok "Precompiler run VERIFIED." }
else { Write-Warn2 "Could NOT verify the precompiler ran. An ON 'PASS' may be a false negative -- check the ASI loaded + point -LogPath at the precompile log." }

if ($Json) {
    $dir = Split-Path -Parent $Json; if ($dir) { New-DirIfMissing $dir }
    $result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $Json -Encoding UTF8
}
$result
