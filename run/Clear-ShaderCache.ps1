#requires -Version 5.1
<#
.SYNOPSIS
  Clear the GPU driver's on-disk shader cache so the OFF baseline run pays the
  COLD first-use shader/pipeline compile cost (that's the stutter we measure).
  Handles NVIDIA, AMD and Intel, plus the DirectX D3DSCache. Supports -WhatIf.

.DESCRIPTION
  On native D3D9, "shader stutter" is the driver JIT-compiling GPU ISA the first
  time it sees a shader+state, and drivers CACHE that ISA on disk keyed to the
  driver version. If the cache is warm, the OFF run won't stutter and the A/B is
  meaningless. So we clear the vendor cache before EACH run (OFF and ON). The
  precompiler's whole job is to make the ON run's cache warm at LAUNCH instead of
  during gameplay.

  Close the game (and ideally the launcher) before clearing -- open handles are
  skipped. Some entries may be locked by the running driver; those are reported
  and skipped (harmless -- they just get rebuilt).

.PARAMETER Vendor
  Auto (default, detect from the active GPU), NVIDIA, AMD, Intel, or All.
.EXAMPLE
  .\Clear-ShaderCache.ps1 -Vendor Auto
  .\Clear-ShaderCache.ps1 -Vendor All -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet('Auto','NVIDIA','AMD','Intel','All')]
    [string]$Vendor = 'Auto'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'
$LA = $env:LOCALAPPDATA
$PD = $env:ProgramData

# Known driver shader-cache locations per vendor (folders whose CONTENTS we clear).
$CacheMap = @{
    NVIDIA = @(
        (Join-Path $LA 'NVIDIA\DXCache'),
        (Join-Path $LA 'NVIDIA\GLCache'),
        (Join-Path $LA 'NVIDIA\OptixCache'),
        (Join-Path $PD 'NVIDIA Corporation\NV_Cache')
    )
    AMD = @(
        (Join-Path $LA 'AMD\DxCache'),
        (Join-Path $LA 'AMD\DxcCache'),
        (Join-Path $LA 'AMD\DXCache'),
        (Join-Path $LA 'AMD\GLCache'),
        (Join-Path $LA 'AMD\VkCache')
    )
    Intel = @(
        (Join-Path $LA 'Intel\ShaderCache'),
        (Join-Path $LA 'Intel\DXCache')
    )
    # Driver-independent DirectX shader cache (D3D). Clear for all vendors.
    DirectX = @(
        (Join-Path $LA 'D3DSCache')
    )
}

function Resolve-Vendor {
    try {
        foreach ($v in (Get-CimInstance Win32_VideoController -ErrorAction Stop)) {
            $n = ($v.Name + '').ToLowerInvariant()
            if ($n -match 'nvidia|geforce|rtx|gtx') { return 'NVIDIA' }
            if ($n -match 'amd|radeon|rx ')          { return 'AMD' }
            if ($n -match 'intel|arc|iris|uhd|hd graphics') { return 'Intel' }
        }
    } catch {}
    return 'All'
}

function Clear-Folder {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return [pscustomobject]@{ path=$Path; state='absent'; removed=0; skipped=0 } }
    $removed = 0; $skipped = 0
    $items = Get-ChildItem -LiteralPath $Path -Recurse -Force -ErrorAction SilentlyContinue
    foreach ($it in $items) {
        if ($it.PSIsContainer) { continue }
        if ($PSCmdlet.ShouldProcess($it.FullName, 'Remove shader-cache file')) {
            try { Remove-Item -LiteralPath $it.FullName -Force -ErrorAction Stop; $removed++ }
            catch { $skipped++ }
        }
    }
    # Remove now-empty subdirectories (best effort).
    Get-ChildItem -LiteralPath $Path -Recurse -Force -Directory -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending | ForEach-Object {
            if ($PSCmdlet.ShouldProcess($_.FullName, 'Remove empty cache dir')) {
                try { Remove-Item -LiteralPath $_.FullName -Force -Recurse -ErrorAction SilentlyContinue } catch {}
            }
        }
    return [pscustomobject]@{ path=$Path; state='cleared'; removed=$removed; skipped=$skipped }
}

$target = if ($Vendor -eq 'Auto') { Resolve-Vendor } else { $Vendor }
Write-Host "Clearing shader cache for vendor: $target (WhatIf=$($WhatIfPreference))"

$toClear = @()
if ($target -eq 'All') { $toClear += $CacheMap.NVIDIA + $CacheMap.AMD + $CacheMap.Intel }
elseif ($CacheMap.ContainsKey($target)) { $toClear += $CacheMap[$target] }
$toClear += $CacheMap.DirectX

$results = @()
foreach ($p in ($toClear | Select-Object -Unique)) {
    $r = Clear-Folder -Path $p
    $results += $r
    $msg = "{0,-8} {1}  (removed {2}, skipped {3})" -f $r.state, $r.path, $r.removed, $r.skipped
    if ($r.state -eq 'cleared') { Write-Host "  $msg" -ForegroundColor Green } else { Write-Host "  $msg" -ForegroundColor DarkGray }
}
$totalRemoved = ($results | Measure-Object -Property removed -Sum).Sum
$totalSkipped = ($results | Measure-Object -Property skipped -Sum).Sum
Write-Host "Done. Files removed: $totalRemoved  skipped(locked): $totalSkipped"
if ($totalSkipped -gt 0) {
    Write-Warning "Some files were locked (driver/game running). Close GTA IV + the launcher and re-run for a fully cold cache."
}
$results
