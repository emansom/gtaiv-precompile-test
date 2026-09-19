# GTA IV save games

Five saves copied out of the Linux (Proton) prefix so a Windows run can start from
the same place in the world the Linux capture was made from.

```
SGTA400  SGTA401  SGTA412  SGTA413  SGTA414
```

Install them with:

```powershell
.\run\Install-Saves.ps1
```

## Why this matters for the measurement, not just convenience

The point of the Windows run is to compare its pipeline keys against the Linux ones.
If Windows starts somewhere else in the game, any difference in the key sets has two
possible explanations — a genuine platform difference, or simply different scenery —
and the experiment cannot tell them apart. Loading the same save removes that
confound.

## The destination folder is not fixed

Saves live in:

```
%USERPROFILE%\Documents\Rockstar Games\GTA IV\Profiles\<ID>\
```

`<ID>` is an 8-hex-digit folder GTA IV derives per user. The Linux profile is
`3B1E0C2A`; **Windows will have a different one**, so nothing can be hardcoded.
Launch GTA IV once and quit — that creates the folder — then run the script, which
auto-detects it (and backs up any saves already there).

## Known ways this goes wrong

- **Social Club cloud saves can overwrite local ones** on the next launch. If a save
  you expect is missing in-game, go offline or disable cloud saves, then copy again.
- **Not included on purpose:** `ProfileSettings` (the game's own graphics settings)
  and `ControlMap.dat`. Those are per-machine, and overwriting the Windows ones with
  Linux values would change the very settings the test is supposed to observe. Only
  the `SGTA*` saves are carried across.
- These are the **owner's personal saves**, committed to a public repository
  deliberately so the Windows session can reproduce the run. They are binary game
  state with no account credentials in them.
