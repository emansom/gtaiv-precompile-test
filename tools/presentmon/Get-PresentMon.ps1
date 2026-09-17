#requires -Version 5.1
<#
.SYNOPSIS
  Download the pinned PresentMon CLI (Intel/MS, MIT-licensed) next to this script.
  We pin v1.10.0: a single self-contained .exe with a simple CLI and the classic
  CSV columns (msBetweenPresents) the analyzer expects.

.DESCRIPTION
  We do NOT bundle the binary in the repo (keeps it source-only + lets you verify
  the download). PresentMon's license is MIT, so bundling is permitted if you
  later choose to. This script fetches the pinned release from GitHub and, if you
  provide -ExpectedSha256 (or fill $DefaultSha256 below), verifies it.

.NOTES
  Author cannot compute the real hash offline, so $DefaultSha256 is empty by
  default: the script prints the downloaded file's SHA256 for you to record/pin.
  PresentMon 2.x also works but has a different CLI/CSV -- see README; prefer 1.x.
#>
[CmdletBinding()]
param(
    [string]$Version = '1.10.0',
    [string]$ExpectedSha256 = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$DefaultSha256 = ''   # <- pin here once you've recorded a trusted hash.
if (-not $ExpectedSha256) { $ExpectedSha256 = $DefaultSha256 }

$asset = "PresentMon-$Version-x64.exe"
$url = "https://github.com/GameTechDev/PresentMon/releases/download/v$Version/$asset"
$dest = Join-Path $PSScriptRoot $asset
$stable = Join-Path $PSScriptRoot 'PresentMon.exe'   # version-agnostic name the harness calls

if (Test-Path -LiteralPath $stable) {
    Write-Host "PresentMon already present: $stable"
    return $stable
}

Write-Host "Downloading $url"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try {
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
} catch {
    Write-Error "Download failed: $_`nGet PresentMon manually from https://github.com/GameTechDev/PresentMon/releases and save it as: $stable"
    return
}

$hash = (Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash
Write-Host "SHA256: $hash"
if ($ExpectedSha256) {
    if ($hash -ieq $ExpectedSha256) { Write-Host "hash verified OK" -ForegroundColor Green }
    else { Remove-Item -LiteralPath $dest -Force; Write-Error "HASH MISMATCH (expected $ExpectedSha256) -- deleted download."; return }
} else {
    Write-Warning "No expected hash pinned; RECORD the SHA256 above and pin it in this script / README before trusting the binary."
}

Copy-Item -LiteralPath $dest -Destination $stable -Force
Write-Host "PresentMon ready: $stable"
return $stable
