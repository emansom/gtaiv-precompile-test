#requires -Version 5.1
<#
.SYNOPSIS
  Clear the GPU driver's on-disk shader cache so the OFF baseline run pays the
  COLD first-use shader/pipeline compile cost (that's the stutter we measure).
  Handles NVIDIA, AMD and Intel, plus the DirectX D3DSCache. Supports -WhatIf.

.DESCRIPTION
  "Shader stutter" is the first-use compile cost: under DXVK a Vulkan PIPELINE is
  built the first time the game draws with a given shader+state, and both the Vulkan
  driver and (on older DXVK) DXVK itself CACHE the result on disk. If those caches
  are warm, the OFF run won't stutter and the A/B is meaningless. So we clear them
  before EACH run (OFF and ON). The precompiler's whole job is to make the ON run's
  cache warm at LAUNCH instead of during gameplay.

  Every run uses DXVK (see CLAUDE.md -- a native-D3D9 run makes the game load
  different shader bytecode entirely and is not comparable), so the cache that
  matters is the vendor's VULKAN pipeline cache, plus any *.dxvk-cache beside the
  executable. The D3D9-era entries are still cleared: harmless, and cheap.

  Close the game (and ideally the launcher) before clearing -- open handles are
  skipped. Some entries may be locked by the running driver; those are reported
  and skipped (harmless -- they just get rebuilt).

.PARAMETER Vendor
  Auto (default, detect from the active GPU), NVIDIA, AMD, Intel, or All.
.PARAMETER GamePath
  Folder containing GTAIV.exe. When given, DXVK's own state-cache files
  (*.dxvk-cache) are removed from it too. DXVK 2.x dropped the state cache in favour
  of pipeline libraries, so on a current build there is usually nothing to remove --
  absence is the expected result, not a failure.
.EXAMPLE
  .\Clear-ShaderCache.ps1 -Vendor Auto -GamePath "D:\Games\GTAIV"
  .\Clear-ShaderCache.ps1 -Vendor All -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet('Auto','NVIDIA','AMD','Intel','All')]
    [string]$Vendor = 'Auto',
    [string]$GamePath
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
        (Join-Path $LA 'AMD\VkCache'),
        # Measured on a Windows 11 / RX 9070 XT box: the driver also keeps
        # AMD\DX9Cache (9.2 MB seen) and AMD\OglCache, neither of which was in this
        # list. DX9Cache only matters if a run ever falls back to native D3D9 -- but
        # leaving a shader cache behind is exactly how a "cold" baseline silently
        # comes up warm, so clear them too. Note AMD\VkCache was EMPTY on that
        # machine even mid-Vulkan-session, so it is not where this driver caches.
        (Join-Path $LA 'AMD\DX9Cache'),
        (Join-Path $LA 'AMD\OglCache')
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
# DXVK 2.x/3.x keeps its OWN Vulkan pipeline cache per-application in
# %LOCALAPPDATA%\dxvk\<hash>.dxvk.bin (+ .lut). This is NOT the old 1.x state cache
# and NOT the vendor cache cleared above -- it survives both, and DXVK reports it at
# startup as "Found cache file: ... / Cache: <N> shaders". Leaving it in place is the
# single most likely way to get a warm "cold" baseline: the OFF run then shows no
# spikes and the A/B reads INCONCLUSIVE for a reason that looks exactly like the
# legitimate GPL-on "nothing to fix here" result. Measured on this machine: 10 MB /
# 1728 shaders still cached after the vendor caches were cleared.
$dxvkAppCache = Join-Path $env:LOCALAPPDATA 'dxvk'
if (Test-Path -LiteralPath $dxvkAppCache) {
    $r = Clear-Folder -Path $dxvkAppCache
    $results += $r
    $msg = "{0,-8} {1}  (removed {2}, skipped {3})" -f $r.state, $r.path, $r.removed, $r.skipped
    if ($r.state -eq 'cleared') { Write-Host "  $msg" -ForegroundColor Green } else { Write-Host "  $msg" -ForegroundColor DarkGray }
} else {
    Write-Host "  absent   $dxvkAppCache" -ForegroundColor DarkGray
}

# DXVK's old 1.x state cache lived beside the executable. DXVK 2.x dropped it in
# favour of pipeline libraries, so finding nothing here is the expected result on a
# current build -- not a failure.
if ($GamePath -and (Test-Path -LiteralPath $GamePath)) {
    $dxvk = Get-ChildItem -LiteralPath $GamePath -Filter '*.dxvk-cache' -File -ErrorAction SilentlyContinue
    if ($dxvk) {
        foreach ($f in $dxvk) {
            if ($PSCmdlet.ShouldProcess($f.FullName, 'Remove DXVK state cache')) {
                try {
                    Remove-Item -LiteralPath $f.FullName -Force -ErrorAction Stop
                    Write-Host "  cleared  $($f.FullName)" -ForegroundColor Green
                    $results += [pscustomobject]@{ path=$f.FullName; state='cleared'; removed=1; skipped=0 }
                } catch {
                    Write-Host "  locked   $($f.FullName)" -ForegroundColor DarkGray
                    $results += [pscustomobject]@{ path=$f.FullName; state='locked'; removed=0; skipped=1 }
                }
            }
        }
    } else {
        Write-Host "  absent   no *.dxvk-cache in $GamePath (expected on DXVK 2.x)" -ForegroundColor DarkGray
    }
}

$totalRemoved = ($results | Measure-Object -Property removed -Sum).Sum
$totalSkipped = ($results | Measure-Object -Property skipped -Sum).Sum
Write-Host "Done. Files removed: $totalRemoved  skipped(locked): $totalSkipped"
if ($totalSkipped -gt 0) {
    Write-Warning "Some files were locked (driver/game running). Close GTA IV + the launcher and re-run for a fully cold cache."
}
$results
