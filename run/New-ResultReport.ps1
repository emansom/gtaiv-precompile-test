#requires -Version 5.1
<#
.SYNOPSIS
  Build the ready-to-post GitHub issue COMMENT (result.md) + machine result.json
  from the hardware, A/B-verdict and precompiler-verify JSONs. The markdown block
  is what you paste/post onto the pinned "Hardware Test Results" issue (#1) so
  results from many machines aggregate in one consistent schema.

.EXAMPLE
  .\New-ResultReport.ps1 -HardwareJson .\results\raw\hardware.json `
     -VerdictJson .\results\raw\verdict.json -VerifyJson .\results\raw\verify.json `
     -OutMd .\results\result.md -OutJson .\results\result.json
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$HardwareJson,
    [Parameter(Mandatory=$true)][string]$VerdictJson,
    [string]$VerifyJson,
    [int]$RouteSeconds = 90,
    [string]$FusionFixBranch = 'shader-precompile-cache',
    [string]$FusionFixCommit,
    [string]$Notes,
    [string]$HarnessVersion = 'v1',
    [Parameter(Mandatory=$true)][string]$OutMd,
    [string]$OutJson
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$SCHEMA = 'gtaiv-precompile-result/v1'
# This file is pasted into a shared issue: force '.' decimals so a tester on a
# comma-decimal locale does not publish '94,83' where readers expect '94.83'.
[System.Threading.Thread]::CurrentThread.CurrentCulture =
    [System.Globalization.CultureInfo]::InvariantCulture

function Read-Json($p) {
    if ($p -and (Test-Path -LiteralPath $p)) { return (Get-Content -LiteralPath $p -Raw | ConvertFrom-Json) }
    return $null
}
# NB: -f binds tighter than +, so the concatenation MUST be parenthesised or this
# parses as '{0:' + $fmt + ('}' -f $v) and throws "Format item ends prematurely".
function N($v, $fmt='F1') { if ($null -eq $v) { return 'n/a' } return (('{0:' + $fmt + '}') -f [double]$v) }

$hw = Read-Json $HardwareJson
$vd = Read-Json $VerdictJson
$vf = Read-Json $VerifyJson
if (-not $vd) { throw "verdict JSON not found/readable: $VerdictJson" }

# Analyzer JSON: reports = [OFF, ON]; comparison.verdict = PASS/FAIL.
$off = $vd.reports[0]
$on  = $vd.reports[1]
$verdict = if ($vd.comparison) { $vd.comparison.verdict } else { 'N/A' }
$emoji = if ($verdict -eq 'PASS') { 'PASS ✅' } elseif ($verdict -eq 'FAIL') { 'FAIL ❌' } else { $verdict }

# Hardware strings.
$gpu = 'unknown'; $drv = 'n/a'; $vendor = 'n/a'
if ($hw -and $hw.primary_gpu) { $gpu = $hw.primary_gpu.Name; $drv = $hw.primary_gpu.DriverVersion; $vendor = $hw.vendor }
$cpu = if ($hw -and $hw.cpu) { "$($hw.cpu.Name) ($($hw.cpu.Cores)C/$($hw.cpu.Threads)T)" } else { 'n/a' }
$osStr = if ($hw -and $hw.os) { "$($hw.os.Caption) $($hw.os.DisplayVersion) (build $($hw.os.Build).$($hw.os.UBR))" } else { 'n/a' }
$ram = if ($hw) { "$($hw.ram_gb) GB" } else { 'n/a' }

# Precompiler verify strings.
$commit = $FusionFixCommit
if (-not $commit -and $vf -and $vf.fusionfix_commit) { $commit = $vf.fusionfix_commit }
if (-not $commit) { $commit = 'unknown' }
$precompileStr = 'not verified'
$precompileMs = $null; $shaderCount = $null
if ($vf) {
    $shaderCount = $vf.shader_count
    $precompileMs = $vf.precompile_ms
    if ($vf.verified) {
        $sec = if ($precompileMs) { " in {0:F1} s" -f ($precompileMs/1000.0) } else { '' }
        $pl = if ($vf.pipeline_count) { ", $($vf.pipeline_count) pipelines" } else { '' }
        $precompileStr = "verified -- $shaderCount shaders$pl$sec at launch"
    } else {
        $precompileStr = "NOT verified (result may be unreliable -- see Verify-Precompiler)"
    }
}

# No per-pipeline-compile counter is exposed to the game, so the isolated
# compile-stutter spike count stands in for "pipelines built during gameplay".
$offSpikes = [int]$off.isolated_spike_count
$onSpikes  = [int]$on.isolated_spike_count

$md = @()
$md += "### GTA IV Shader-Precompile Result -- $emoji"
$md += ""
$md += "| field | value |"
$md += "|---|---|"
$md += "| **Verdict** | **$emoji** |"
$md += "| GPU | $gpu -- driver ``$drv`` [$vendor] |"
$md += "| CPU | $cpu |"
$md += "| OS | $osStr |"
$md += "| RAM | $ram |"
$md += "| FusionFix ASI | ``$FusionFixBranch`` @ ``$commit`` |"
$md += "| Precompiler | $precompileStr |"
$md += "| Route | ${RouteSeconds}s fixed drive, driver shader cache cleared before each run |"
$md += "| Harness | gtaiv-precompile-test $HarnessVersion |"
$md += ""
$md += "**Frame-time A/B (precompile OFF cold-cache -> ON):**"
$md += ""
$md += "| metric | OFF (cold) | ON |"
$md += "|---|---:|---:|"
$md += "| isolated compile-stutter spikes | $offSpikes | **$onSpikes** |"
$md += "| in-gameplay compiles (~= spikes) | $offSpikes | **$onSpikes** |"
$md += "| p99 frame time (ms) | $(N $off.p99_ms) | $(N $on.p99_ms) |"
$md += "| p99.9 frame time (ms) | $(N $off.p999_ms) | $(N $on.p999_ms) |"
$md += "| max frame time (ms) | $(N $off.max_ms) | $(N $on.max_ms) |"
$md += "| total stutter time (ms) | $(N $off.total_excess_ms 'F0') | $(N $on.total_excess_ms 'F0') |"
$md += "| median frame time (ms) | $(N $off.median_ms 'F2') | $(N $on.median_ms 'F2') |"
$md += ""
$md += "<details><summary>run details</summary>"
$md += ""
$md += "- frames OFF/ON: $($off.n_frames) / $($on.n_frames); duration $(N $off.duration_s)s / $(N $on.duration_s)s"
$md += "- capture: PresentMon (present-to-present); source ``$($off.source)``"
$md += "- spike gate: excess>=$($off.thresholds.excess_floor_ms)ms AND (dt>=$($off.thresholds.rel_factor)x baseline OR >$($off.thresholds.mad_k)*MAD), window=$($off.thresholds.window)"
if ($shaderCount) { $md += "- precompiler: $shaderCount shaders warmed at launch" }
if ($Notes) { $md += "- notes: $Notes" }
$md += ""
$md += "</details>"
$md += ""
$md += "<!-- schema: $SCHEMA -->"

$mdText = ($md -join "`n")
$dir = Split-Path -Parent $OutMd; if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
Set-Content -LiteralPath $OutMd -Value $mdText -Encoding UTF8
Write-Host "wrote $OutMd" -ForegroundColor Green
Write-Host ""
Write-Host $mdText

if ($OutJson) {
    $obj = [pscustomobject]@{
        schema = $SCHEMA
        verdict = $verdict
        gpu = $gpu; gpu_driver = $drv; vendor = $vendor
        cpu = $cpu; os = $osStr; ram = $ram
        fusionfix_branch = $FusionFixBranch; fusionfix_commit = $commit
        precompiler_verified = $(if ($vf) { [bool]$vf.verified } else { $false })
        precompile_ms = $precompileMs; shaders_precompiled = $shaderCount
        route_seconds = $RouteSeconds
        off = [pscustomobject]@{ isolated_spikes=$offSpikes; p99_ms=$off.p99_ms; p999_ms=$off.p999_ms; max_ms=$off.max_ms; total_excess_ms=$off.total_excess_ms; median_ms=$off.median_ms; frames=$off.n_frames }
        on  = [pscustomobject]@{ isolated_spikes=$onSpikes;  p99_ms=$on.p99_ms;  p999_ms=$on.p999_ms;  max_ms=$on.max_ms;  total_excess_ms=$on.total_excess_ms; median_ms=$on.median_ms; frames=$on.n_frames }
    }
    $obj | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $OutJson -Encoding UTF8
    Write-Host "wrote $OutJson" -ForegroundColor Green
}
