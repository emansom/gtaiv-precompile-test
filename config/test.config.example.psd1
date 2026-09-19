@{
    # ---- gtaiv-precompile-test config ---------------------------------------
    # Copy this file to  config\test.config.psd1  and edit for your machine.
    # This is a DATA file (Import-PowerShellDataFile) -- no code runs from it.

    # Path to the GTAIV folder that contains GTAIV.exe. Leave $null to auto-detect
    # under common Steam / Rockstar install locations.
    GamePath        = $null
    # e.g. GamePath = 'D:\SteamLibrary\steamapps\common\Grand Theft Auto IV\GTAIV'

    # Seconds to capture per run (same for OFF and ON). 60-120 is typical.
    RouteSeconds    = 90

    # ---- Precompiler ASI + how to toggle it ON/OFF --------------------------
    # Built .asi from github.com/emansom/GTAIV.EFLC.FusionFix branch shader-precompile-cache
    # (prebuilt\ has one; shader-precompile is an older diverged line).
    # If it's already installed in the game's plugins\, you can leave AsiPath $null.
    AsiPath         = $null
    AsiName         = 'GTAIV.EFLC.FusionFix.asi'

    # ToggleMode:
    #   'ConfigKey'   flip an INI key the precompiler reads (keeps FusionFix loaded
    #                 both runs -- isolates just the precompile step). Set the keys
    #                 to match the precompiler's real setting (check the FusionFix
    #                 .ini, or ask the mod author).
    #   'AsiPresence' the precompiler is a standalone .asi: OFF unloads it.
    ToggleMode      = 'ConfigKey'
    ConfigFile      = 'plugins\GTAIV.EFLC.FusionFix.ini'
    ConfigSection   = 'SHADERS'
    ConfigKey       = 'PrecompileShaders'

    # ---- Provenance for the shared result -----------------------------------
    FusionFixBranch = 'shader-precompile-cache'
    FusionFixCommit = $null      # set the ASI's git commit if you know it
    Notes           = $null      # anything worth sharing (route description, quirks)
}
