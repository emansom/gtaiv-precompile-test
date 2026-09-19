#requires -Version 5.1
<#
.SYNOPSIS
  Copy this repo's GTA IV save games into the Windows profile so the Windows run can
  load the same saves the Linux capture was made from.

.DESCRIPTION
  Saves live in %USERPROFILE%\Documents\Rockstar Games\GTA IV\Profiles\<ID>\, where
  <ID> is an 8-hex-digit folder GTA IV derives per user -- it is NOT the same value
  across installs. The Linux profile is 3B1E0C2A; Windows will have its own. So the
  destination cannot be hardcoded: the game must be launched once to create its
  profile folder, and the saves go into whatever folder that turns out to be.

  Existing SGTA* files are backed up next to them before anything is overwritten.

  Comparability matters more than it looks: loading the same save means the Windows
  capture starts from the same place in the world as the Linux one, so the two key
  sets can be diffed without "they drove somewhere else" as a confound.

.PARAMETER ProfileId
  Target profile folder name. Omit to auto-detect (the only one, or the most recently
  written if there are several).
.PARAMETER Source
  Folder holding the SGTA* files. Defaults to ..\saves\profile relative to this script.
.PARAMETER Force
  Overwrite without prompting.
.EXAMPLE
  .\run\Install-Saves.ps1
  .\run\Install-Saves.ps1 -ProfileId A1B2C3D4 -Force
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ProfileId,
    [string]$Source,
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $Source) { $Source = Join-Path (Split-Path -Parent $PSScriptRoot) 'saves\profile' }
if (-not (Test-Path -LiteralPath $Source)) { throw "No save source at $Source" }

$saves = Get-ChildItem -LiteralPath $Source -Filter 'SGTA*' -File
if (-not $saves) { throw "No SGTA* files in $Source" }

$profilesRoot = Join-Path $env:USERPROFILE 'Documents\Rockstar Games\GTA IV\Profiles'
if (-not (Test-Path -LiteralPath $profilesRoot)) {
    Write-Warning "$profilesRoot does not exist."
    Write-Warning "Launch GTA IV once and quit -- the game creates its profile folder on first run -- then re-run this."
    return
}

$dirs = @(Get-ChildItem -LiteralPath $profilesRoot -Directory -ErrorAction SilentlyContinue)
if ($ProfileId) {
    $target = Join-Path $profilesRoot $ProfileId
    if (-not (Test-Path -LiteralPath $target)) { throw "No such profile folder: $target" }
} elseif ($dirs.Count -eq 1) {
    $target = $dirs[0].FullName
} elseif ($dirs.Count -gt 1) {
    # Several profiles: the one the game touched last is the one in use.
    $target = ($dirs | Sort-Object LastWriteTime -Descending)[0].FullName
    Write-Warning "$($dirs.Count) profile folders found; using the most recently written:"
    Write-Warning "  $target"
    Write-Warning "Pass -ProfileId to choose a different one: $($dirs.Name -join ', ')"
} else {
    Write-Warning "$profilesRoot has no profile folders yet."
    Write-Warning "Launch GTA IV once and quit, then re-run this."
    return
}

Write-Host "Source : $Source"
Write-Host "Target : $target"
Write-Host "Saves  : $($saves.Name -join ', ')"

# Back up whatever is already there before touching it.
$existing = Get-ChildItem -LiteralPath $target -Filter 'SGTA*' -File -ErrorAction SilentlyContinue
if ($existing) {
    $backup = Join-Path $target ("saves-backup-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    if ($PSCmdlet.ShouldProcess($backup, "Back up $($existing.Count) existing save(s)")) {
        New-Item -ItemType Directory -Force -Path $backup | Out-Null
        foreach ($e in $existing) { Copy-Item -LiteralPath $e.FullName -Destination $backup -Force }
        Write-Host "Backed up $($existing.Count) existing save(s) to $backup" -ForegroundColor Yellow
    }
} else {
    Write-Host "No existing saves in the target profile." -ForegroundColor DarkGray
}

if (-not $Force -and $existing) {
    $ans = Read-Host "Overwrite $($existing.Count) existing save(s) with $($saves.Count) from the repo? [y/N]"
    if ($ans -notmatch '^[Yy]') { Write-Host "Aborted; nothing copied."; return }
}

$n = 0
foreach ($s in $saves) {
    $dest = Join-Path $target $s.Name
    if ($PSCmdlet.ShouldProcess($dest, 'Copy save')) {
        Copy-Item -LiteralPath $s.FullName -Destination $dest -Force
        $n++
    }
}
Write-Host "Copied $n save(s) into $target" -ForegroundColor Green
Write-Host ""
Write-Host "If GTA IV is signed in to the Social Club, its cloud saves can overwrite these"
Write-Host "on the next launch. If a save you expect is missing in-game, disable cloud saves"
Write-Host "(or go offline) and copy again."
