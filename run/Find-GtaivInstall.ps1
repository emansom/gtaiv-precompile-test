#requires -Version 5.1
<#
.SYNOPSIS
  Locate every GTA IV installation on this machine -- Steam and Rockstar Games
  Launcher / retail -- and return where GTAIV.exe actually lives.

.DESCRIPTION
  The harness used to guess three hardcoded paths under Program Files. That misses
  almost everyone: Steam libraries live on whatever drive the user put them on, and
  the Rockstar Games Launcher installs somewhere else again. Ask the installers
  instead of guessing.

  STEAM
    1. Registry -> Steam root: HKCU\Software\Valve\Steam::SteamPath, falling back to
       HKLM\...\WOW6432Node\Valve\Steam::InstallPath.
    2. <steam>\steamapps\libraryfolders.vdf lists EVERY library folder, one "path"
       per entry. A user with the game on D: has it here and nowhere else.
    3. <library>\steamapps\appmanifest_<appid>.acf gives "installdir"; the game is at
       <library>\steamapps\common\<installdir>.
       12210 = Grand Theft Auto IV / The Complete Edition, 12220 = Episodes From
       Liberty City.

  ROCKSTAR GAMES LAUNCHER / RETAIL
    Titles register HKLM\SOFTWARE\[WOW6432Node\]Rockstar Games\<Title>::InstallFolder.
    Plus a sweep of the Windows uninstall entries for a DisplayName matching GTA IV,
    which catches launcher variants that use a different key name.

  Every candidate is then confirmed by actually finding GTAIV.exe: the Complete
  Edition keeps it in a GTAIV subfolder, older installs keep it at the root, so both
  are probed. A path that does not contain the exe is not returned.

.PARAMETER Json
  Write the results to this file as JSON as well as returning them.
.EXAMPLE
  .\Find-GtaivInstall.ps1
  .\Find-GtaivInstall.ps1 -Json .\results\raw\installs.json
#>
[CmdletBinding()]
param([string]$Json)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Continue'

# GTA IV on Steam. 12210 covers both the original and the Complete Edition (the
# Complete Edition replaced it under the same appid).
$SteamAppIds = @('12210', '12220')

function Get-RegValue {
    param([string]$Path, [string]$Name)
    try {
        $p = Get-ItemProperty -Path $Path -Name $Name -ErrorAction Stop
        return $p.$Name
    } catch { return $null }
}

function Get-VdfPairs {
    # VDF/ACF are "key" "value" per line, nested in braces we do not need to model
    # for these two files. Backslashes are doubled in the file, so unescape them.
    param([string]$Path)
    $pairs = @()
    if (-not (Test-Path -LiteralPath $Path)) { return $pairs }
    foreach ($line in (Get-Content -LiteralPath $Path -ErrorAction SilentlyContinue)) {
        $m = [regex]::Match($line, '"([^"]+)"\s+"([^"]*)"')
        if ($m.Success) {
            $pairs += [pscustomobject]@{
                Key   = $m.Groups[1].Value
                Value = $m.Groups[2].Value -replace '\\\\', '\'
            }
        }
    }
    return $pairs
}

function Get-SteamRoot {
    $p = Get-RegValue 'HKCU:\Software\Valve\Steam' 'SteamPath'
    if (-not $p) { $p = Get-RegValue 'HKLM:\SOFTWARE\WOW6432Node\Valve\Steam' 'InstallPath' }
    if (-not $p) { $p = Get-RegValue 'HKLM:\SOFTWARE\Valve\Steam' 'InstallPath' }
    if (-not $p) { return $null }
    # SteamPath is stored with forward slashes.
    return ($p -replace '/', '\')
}

function Get-SteamLibraries {
    param([string]$SteamRoot)
    $libs = @()
    if (-not $SteamRoot) { return $libs }
    $libs += $SteamRoot
    $vdf = Join-Path $SteamRoot 'steamapps\libraryfolders.vdf'
    foreach ($kv in (Get-VdfPairs $vdf)) {
        # Modern Steam: "path" "D:\\SteamLibrary". Legacy: "1" "D:\\SteamLibrary".
        $isPath = ($kv.Key -eq 'path') -or (($kv.Key -match '^\d+$') -and ($kv.Value -match '^[A-Za-z]:\\|^\\\\'))
        if ($isPath -and $kv.Value) { $libs += $kv.Value }
    }
    return ($libs | Where-Object { $_ } | Select-Object -Unique)
}

function Resolve-ExeDir {
    # The Complete Edition puts GTAIV.exe in a GTAIV subfolder; older installs put it
    # at the root. Return whichever actually holds the exe, else $null.
    param([string]$Root)
    if (-not $Root) { return $null }
    foreach ($sub in @('GTAIV', '')) {
        $dir = if ($sub) { Join-Path $Root $sub } else { $Root }
        if (Test-Path -LiteralPath (Join-Path $dir 'GTAIV.exe')) {
            return (Resolve-Path -LiteralPath $dir).Path
        }
    }
    return $null
}

$found = @()

# ---- Steam ----------------------------------------------------------------
$steamRoot = Get-SteamRoot
if ($steamRoot) {
    Write-Verbose "Steam root: $steamRoot"
    foreach ($lib in (Get-SteamLibraries $steamRoot)) {
        foreach ($appid in $SteamAppIds) {
            $acf = Join-Path $lib "steamapps\appmanifest_$appid.acf"
            if (-not (Test-Path -LiteralPath $acf)) { continue }
            $pairs = Get-VdfPairs $acf
            $installdir = ($pairs | Where-Object { $_.Key -eq 'installdir' } | Select-Object -First 1).Value
            $name = ($pairs | Where-Object { $_.Key -eq 'name' } | Select-Object -First 1).Value
            if (-not $installdir) { continue }
            $root = Join-Path $lib "steamapps\common\$installdir"
            $exeDir = Resolve-ExeDir $root
            if ($exeDir) {
                $found += [pscustomobject]@{
                    Source = 'Steam'; AppId = $appid; Name = $name
                    Root = $root; ExeDir = $exeDir; Exe = (Join-Path $exeDir 'GTAIV.exe')
                }
            } else {
                Write-Verbose "appmanifest $appid points at $root but no GTAIV.exe there"
            }
        }
    }
}

# ---- Rockstar Games Launcher / retail --------------------------------------
$rsKeys = @(
    'HKLM:\SOFTWARE\WOW6432Node\Rockstar Games',
    'HKLM:\SOFTWARE\Rockstar Games'
)
foreach ($base in $rsKeys) {
    if (-not (Test-Path -LiteralPath $base)) { continue }
    foreach ($sub in (Get-ChildItem -LiteralPath $base -ErrorAction SilentlyContinue)) {
        if ($sub.PSChildName -notmatch 'Grand Theft Auto IV|GTAIV|Episodes') { continue }
        foreach ($valName in @('InstallFolder', 'InstallLocation', 'Install Folder')) {
            $root = Get-RegValue $sub.PSPath $valName
            if (-not $root) { continue }
            $exeDir = Resolve-ExeDir $root
            if ($exeDir) {
                $found += [pscustomobject]@{
                    Source = 'Rockstar'; AppId = ''; Name = $sub.PSChildName
                    Root = $root; ExeDir = $exeDir; Exe = (Join-Path $exeDir 'GTAIV.exe')
                }
            }
            break
        }
    }
}

# ---- Windows uninstall entries (catches launcher variants) ------------------
$uninstallRoots = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
)
foreach ($ur in $uninstallRoots) {
    if (-not (Test-Path -LiteralPath $ur)) { continue }
    foreach ($k in (Get-ChildItem -LiteralPath $ur -ErrorAction SilentlyContinue)) {
        $dn = Get-RegValue $k.PSPath 'DisplayName'
        if (-not $dn -or $dn -notmatch 'Grand Theft Auto IV') { continue }
        $loc = Get-RegValue $k.PSPath 'InstallLocation'
        $exeDir = Resolve-ExeDir $loc
        if ($exeDir) {
            $found += [pscustomobject]@{
                Source = 'Uninstall'; AppId = ''; Name = $dn
                Root = $loc; ExeDir = $exeDir; Exe = (Join-Path $exeDir 'GTAIV.exe')
            }
        }
    }
}

# De-duplicate on the resolved exe directory; prefer Steam, then Rockstar.
$rank = @{ 'Steam' = 0; 'Rockstar' = 1; 'Uninstall' = 2 }
$found = $found |
    Sort-Object @{ Expression = { $rank[$_.Source] } }, ExeDir |
    Group-Object ExeDir |
    ForEach-Object { $_.Group[0] }

if (-not $found -or $found.Count -eq 0) {
    Write-Warning "No GTA IV installation found via Steam, Rockstar or the uninstall entries."
    Write-Warning "Set GamePath explicitly in config\test.config.psd1 (the folder containing GTAIV.exe)."
} else {
    Write-Host "Found $($found.Count) GTA IV installation(s):"
    foreach ($f in $found) {
        Write-Host ("  [{0,-9}] {1}" -f $f.Source, $f.ExeDir)
        if ($f.Name) { Write-Host ("              {0}" -f $f.Name) -ForegroundColor DarkGray }
    }
    if ($found.Count -gt 1) {
        Write-Warning "More than one install. The harness will use the first (Steam preferred); set GamePath to override."
    }
}

if ($Json) {
    $dir = Split-Path -Parent $Json
    if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $found | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $Json -Encoding UTF8
    Write-Host "Wrote $Json"
}

$found
