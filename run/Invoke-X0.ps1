#requires -Version 7.0
<#
.SYNOPSIS
  Run experiment X0: does AMD's Windows Vulkan driver refuse to fast-link a
  graphics-pipeline-library fragment shader that declares BuiltIn PointCoord?
  No game, no DXVK, no elevation. About a minute.

.DESCRIPTION
  Runs tools\x0-llpc-pointcoord\x0.exe (32-bit, like GTA IV) -Runs times. Each run
  gets a fresh, empty AMD pipeline-cache folder, set through the same variables
  Steam sets for GTA IV:
     AMD_VK_PIPELINE_CACHE_PATH     = <new temp folder>
     AMD_VK_PIPELINE_CACHE_FILENAME = steamapp_shader_cache
     AMD_VK_USE_PIPELINE_CACHE      = 1
  x0.exe also makes every shader it compiles unique, so a run is cold even if the
  driver ignores those variables.

  Writes results\raw\x0-run<N>.json + .txt per run, and results\raw\x0.json with
  all runs and one verdict:
     H0_PROVEN     the PointCoord arm never fast-links (slow, COMPILE_REQUIRED)
     H0_FALSIFIED  both arms fast-link
     OTHER         anything else -- report it as-is
     MIXED         the runs disagree -- report every run's line
  How to read it: tools\x0-llpc-pointcoord\README.md.

.EXAMPLE
  .\run\Invoke-X0.ps1
  .\run\Invoke-X0.ps1 -Runs 5 -Iterations 50
#>
[CmdletBinding()]
param(
    [int]$Runs = 3,
    [int]$Iterations = 25,
    # both = the binding model DXVK uses on this GPU (the verdict) + the other one
    [ValidateSet('both','auto','heap','legacy')]
    [string]$Binding = 'both',
    [string]$Json,
    [string]$Exe,
    [switch]$KeepCache
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Common.ps1"

if (-not $Exe)  { $Exe  = Join-Path $RepoRoot 'tools\x0-llpc-pointcoord\x0.exe' }
if (-not $Json) { $Json = Join-Path $RawDir 'x0.json' }
if (-not (Test-Path -LiteralPath $Exe)) { throw "x0.exe not found: $Exe" }
New-DirIfMissing $RawDir
New-DirIfMissing (Split-Path -Parent $Json)

function Get-Prop($obj, [string]$name) {
    if ($null -eq $obj) { return $null }
    $p = $obj.PSObject.Properties[$name]
    if ($p) { return $p.Value }
    return $null
}

$sha = (Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Step "X0: PointCoord fast-link test"
Write-Host "  exe    : $Exe"
Write-Host "  sha256 : $sha   (compare with tools\x0-llpc-pointcoord\README.md)"
Write-Host "  OS     : $([Environment]::OSVersion.VersionString)"
if (Get-Process -Name 'GTAIV','PlayGTAIV' -ErrorAction SilentlyContinue) {
    Write-Warn2 "GTA IV is running. It does not break X0, but it competes for CPU; close it for clean timings."
}

$envNames = 'AMD_VK_PIPELINE_CACHE_PATH','AMD_VK_PIPELINE_CACHE_FILENAME','AMD_VK_USE_PIPELINE_CACHE'
$saved = @{}
foreach ($n in $envNames) { $saved[$n] = [Environment]::GetEnvironmentVariable($n, 'Process') }

$runsOut = @()
$caches = @()
try {
    for ($i = 1; $i -le $Runs; $i++) {
        $cache = Join-Path ([IO.Path]::GetTempPath()) ('x0-amdv1-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path $cache | Out-Null
        $caches += $cache
        $env:AMD_VK_PIPELINE_CACHE_PATH     = $cache
        $env:AMD_VK_PIPELINE_CACHE_FILENAME = 'steamapp_shader_cache'
        $env:AMD_VK_USE_PIPELINE_CACHE      = '1'

        $runJson = Join-Path $RawDir "x0-run$i.json"
        $runLog  = Join-Path $RawDir "x0-run$i.txt"
        Remove-Item -LiteralPath $runJson, $runLog -Force -ErrorAction SilentlyContinue

        Write-Step "run $i of $Runs  (driver cache: $cache, empty)"
        $ErrorActionPreference = 'Continue'   # x0 may print to stderr; that is not a failure
        & $Exe -Json $runJson -Iterations $Iterations -Binding $Binding 2>&1 |
            ForEach-Object { "$_" } | Tee-Object -FilePath $runLog
        $code = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'

        # Did the driver honour the redirect? Evidence, not a requirement: the
        # nonce keeps the run cold either way.
        $files = @(Get-ChildItem -LiteralPath $cache -Recurse -File -ErrorAction SilentlyContinue)
        # (Measure-Object on an empty set has no .Sum under StrictMode, so add by hand)
        [long]$bytes = 0
        foreach ($f in $files) { $bytes += $f.Length }
        if ($files.Count -gt 0) {
            Write-Ok ("driver wrote {0} file(s), {1:N0} bytes to the redirected cache" -f $files.Count, $bytes)
        } else {
            Write-Warn2 "driver wrote nothing to the redirected cache folder (the run is still cold: every shader is unique)"
        }

        $parsed = $null
        if (Test-Path -LiteralPath $runJson) {
            $parsed = Get-Content -LiteralPath $runJson -Raw | ConvertFrom-Json
        }
        $runsOut += [pscustomobject]@{
            run              = $i
            exit_code        = $code
            cache_dir        = $cache
            cache_files      = $files.Count
            cache_bytes      = $bytes
            verdict          = if ($parsed) { Get-Prop $parsed 'verdict' } else { 'ERROR' }
            verdict_line     = if ($parsed) { Get-Prop $parsed 'verdict_line' } else { "x0.exe exited $code without writing JSON" }
            result           = $parsed
        }

        if ($code -eq 2) {
            Write-Warn2 "no VK_EXT_graphics_pipeline_library on this device: nothing to repeat"
            break
        }
        if ($code -ne 0) { Write-Err2 "x0.exe exited with code $code" }
    }
} finally {
    foreach ($n in $envNames) { [Environment]::SetEnvironmentVariable($n, $saved[$n], 'Process') }
    if (-not $KeepCache) {
        foreach ($c in $caches) { Remove-Item -LiteralPath $c -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

$verdicts = @($runsOut | ForEach-Object { $_.verdict })
$unique = @($verdicts | Select-Object -Unique)
$overall = if ($runsOut.Count -eq 0) { 'ERROR' } elseif ($unique.Count -eq 1) { $unique[0] } else { 'MIXED' }

$first = if ($runsOut.Count) { $runsOut[0].result } else { $null }
$dev = Get-Prop $first 'device'

$summary = [ordered]@{
    tool           = 'x0-llpc-pointcoord'
    runner         = 'run/Invoke-X0.ps1'
    utc            = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    exe_sha256     = $sha
    os             = [Environment]::OSVersion.VersionString
    runs_requested = $Runs
    iterations     = $Iterations
    binding        = $Binding
    device         = Get-Prop $dev 'name'
    driver_name    = Get-Prop $dev 'driver_name'
    driver_info    = Get-Prop $dev 'driver_info'
    verdict        = $overall
    run_verdicts   = $verdicts
    verdict_lines  = @($runsOut | ForEach-Object { $_.verdict_line })
    runs           = $runsOut
}
$summary | ConvertTo-Json -Depth 32 | Set-Content -LiteralPath $Json -Encoding UTF8

Write-Host ""
Write-Step "X0 summary ($($runsOut.Count) run(s)) -> $Json"
Write-Host "  device : $(Get-Prop $dev 'name')"
Write-Host "  driver : $(Get-Prop $dev 'driver_name')  $(Get-Prop $dev 'driver_info')"
foreach ($r in $runsOut) { Write-Host ("  run {0}  : {1}" -f $r.run, $r.verdict_line) }
$color = switch ($overall) { 'H0_PROVEN' { 'Green' } 'H0_FALSIFIED' { 'Green' } default { 'Yellow' } }
Write-Host ""
Write-Host "X0 VERDICT: $overall" -ForegroundColor $color
if ($overall -eq 'MIXED') { Write-Warn2 "the runs disagree: report every run's line above, not just this one" }

if ($overall -in @('ERROR','MIXED') -or $runsOut.Count -eq 0) { exit 1 }
exit 0
