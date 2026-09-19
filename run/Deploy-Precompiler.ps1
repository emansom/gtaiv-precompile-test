#requires -Version 5.1
<#
.SYNOPSIS
  Deploy the FusionFix shader-precompiler ASI into the game's plugins\ folder and
  toggle the precompile feature ON or OFF for an A/B run.

.DESCRIPTION
  The precompiler ships in the FusionFix 'shader-precompile-cache' branch
  (github.com/emansom/GTAIV.EFLC.FusionFix). Provide the built .asi via -AsiPath,
  or point -GamePath at a game that already has it in plugins\.

  Toggling ON vs OFF (two supported modes):
    * ConfigKey  (default): flips an INI key the precompiler reads (keeps the
      rest of FusionFix loaded both runs -- isolates just the precompile step).
      Set -ConfigFile/-Section/-Key to match the precompiler's actual setting.
    * AsiPresence: if the precompiler is a STANDALONE .asi, OFF renames it to
      '<name>.asi.off' (unloaded) and ON restores it. Use this when there is no
      config key.

  If you don't know the config key: open the FusionFix .ini in the game folder
  and look for a shader/precompile setting, or just use -Mode AsiPresence with a
  standalone precompiler .asi.

.EXAMPLE
  .\Deploy-Precompiler.ps1 -GamePath "D:\...\GTAIV" -AsiPath .\FusionFix.asi -State On
  .\Deploy-Precompiler.ps1 -GamePath "D:\...\GTAIV" -State Off -Mode ConfigKey -ConfigFile "plugins\GTAIV.EFLC.FusionFix.ini" -Section SHADERS -Key PrecompileShaders
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$GamePath,
    [string]$AsiPath,
    [ValidateSet('On','Off')][string]$State = 'On',
    [ValidateSet('ConfigKey','AsiPresence')][string]$Mode = 'ConfigKey',
    [string]$ConfigFile = 'plugins\GTAIV.EFLC.FusionFix.ini',
    [string]$Section = 'SHADERS',
    [string]$Key = 'PrecompileShaders',
    [string]$AsiName = 'GTAIV.EFLC.FusionFix.asi'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Common.ps1"

if (-not (Test-Path -LiteralPath $GamePath)) { throw "GamePath not found: $GamePath" }
$plugins = Join-Path $GamePath 'plugins'
New-DirIfMissing $plugins

# Ultimate ASI Loader sanity (FusionFix ships dinput8.dll).
if (-not (Test-Path -LiteralPath (Join-Path $GamePath 'dinput8.dll'))) {
    Write-Warn2 "dinput8.dll (Ultimate ASI Loader) not found in game dir -- ASIs won't load. Install FusionFix normally first."
}

# Copy the supplied ASI in (if given).
if ($AsiPath) {
    if (-not (Test-Path -LiteralPath $AsiPath)) { throw "AsiPath not found: $AsiPath" }
    $target = Join-Path $plugins (Split-Path -Leaf $AsiPath)
    Copy-Item -LiteralPath $AsiPath -Destination $target -Force
    Write-Ok "Deployed $(Split-Path -Leaf $AsiPath) -> $plugins"
    $AsiName = Split-Path -Leaf $AsiPath
}

function Set-IniKey {
    param([string]$File, [string]$Sec, [string]$K, [string]$Val)
    if (-not (Test-Path -LiteralPath $File)) {
        # Create a minimal ini with the section+key.
        Set-Content -LiteralPath $File -Value @("[$Sec]", "$K=$Val") -Encoding UTF8
        Write-Warn2 "Config $File did not exist; created it with [$Sec] $K=$Val (verify the precompiler reads this key!)"
        return
    }
    $lines = Get-Content -LiteralPath $File
    $out = New-Object System.Collections.Generic.List[string]
    $inSec = $false; $done = $false; $secSeen = $false
    foreach ($ln in $lines) {
        $t = $ln.Trim()
        # NOT '^\[(.+)\]$': FusionFix's ini documents itself with trailing '//'
        # comments on the SECTION HEADERS too ("[SHADERS]   // Launch-time ...").
        # An end-anchored match never fires there, so $inSec stays false, the key
        # is never found, and the fallback appends a SECOND [SHADERS] section --
        # leaving the original value untouched and the toggle silently inert.
        if ($t -match '^\[([^\]]+)\]') {
            if ($inSec -and -not $done) { $out.Add("$K = $Val"); $done = $true }  # append at end of prev section
            $inSec = ($Matches[1].Trim() -ieq $Sec)
            if ($inSec) { $secSeen = $true }
            $out.Add($ln); continue
        }
        if ($inSec -and $t -match "^\s*$([regex]::Escape($K))\s*=") {
            # Keep the trailing '//' documentation: this file is rewritten on every
            # phase, and stripping it would erode the ini over a few runs.
            $ci = $ln.IndexOf('//')
            $cmt = if ($ci -ge 0) { '   ' + $ln.Substring($ci) } else { '' }
            $out.Add("$K = $Val$cmt"); $done = $true; continue
        }
        $out.Add($ln)
    }
    if ($inSec -and -not $done) { $out.Add("$K=$Val"); $done = $true }
    if (-not $secSeen) { $out.Add("[$Sec]"); $out.Add("$K=$Val"); $done = $true }
    Set-Content -LiteralPath $File -Value $out -Encoding UTF8
}

$val = if ($State -eq 'On') { '1' } else { '0' }

if ($Mode -eq 'ConfigKey') {
    $cfg = if ([IO.Path]::IsPathRooted($ConfigFile)) { $ConfigFile } else { Join-Path $GamePath $ConfigFile }
    Set-IniKey -File $cfg -Sec $Section -K $Key -Val $val
    Write-Ok "Precompile $State via $ConfigFile [$Section] $Key=$val"
}
else {
    $asi = Join-Path $plugins $AsiName
    $off = "$asi.off"
    if ($State -eq 'Off') {
        if (Test-Path -LiteralPath $asi) { Move-Item -LiteralPath $asi -Destination $off -Force; Write-Ok "Precompiler unloaded ($AsiName -> $AsiName.off)" }
        elseif (Test-Path -LiteralPath $off) { Write-Ok "Precompiler already OFF" }
        else { Write-Warn2 "Neither $AsiName nor $AsiName.off found in plugins" }
    } else {
        if (Test-Path -LiteralPath $off) { Move-Item -LiteralPath $off -Destination $asi -Force; Write-Ok "Precompiler loaded ($AsiName.off -> $AsiName)" }
        elseif (Test-Path -LiteralPath $asi) { Write-Ok "Precompiler already ON" }
        else { Write-Warn2 "Provide -AsiPath so the precompiler ASI is present for the ON run" }
    }
}
Write-Host "Reminder: this takes effect on the NEXT game launch. Fully close GTA IV before the run." -ForegroundColor Yellow
