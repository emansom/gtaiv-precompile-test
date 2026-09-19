# Prebuilt ASI

So the Windows session does not have to stand up a build toolchain (premake5 + MSVC +
the vendored DirectX SDK) just to run one experiment.

| file | what it is |
|---|---|
| `GTAIV.EFLC.FusionFix.asi` | the mod, built from the branch below |
| `GTAIV.EFLC.FusionFix.ini` | the matching settings template, with the shader keys documented |

## Provenance

```
repo    emansom/GTAIV.EFLC.FusionFix
branch  shader-precompile-cache
commit  0468057  "shaders: key the replay on DXVK's base pipeline, capture instancing"
built   MSVC 14.51 (x86, /MT) via msvc-wine, the same toolchain and Platform=Win32
        target the project's CI uses
sha256  b003d209bc3061afc06c311d9bb03315da276b825881c8518fa662341670f9b5
size    5,952,512 bytes
```

**This build reads and writes cache format v2 only.** It refuses a v1 file and
moves it aside as `<name>.unmerged` instead of overwriting it. The Windows install
from the 2026-09-19 session still holds a v1 capture in `plugins\`; on first launch
the log says so and a fresh capture starts. The same capture, upgraded to v2, is in
`cache\windows-amd-dxvk\` if that session's coverage should carry on.

Verify it is current before trusting it:

```powershell
Get-FileHash .\prebuilt\GTAIV.EFLC.FusionFix.asi -Algorithm SHA256
git -C <fusionfix-clone> log --oneline -1 origin/shader-precompile-cache
```

If that branch has moved past `0468057`, this binary is **stale**. Build from source
or ask for a fresh one. A stale ASI is the worst failure mode here because everything
still appears to work; it would just be measuring the wrong build.

A quick in-game tell that this build (or newer) is the one loaded: the replay's
summary line reads `... N base identities first (shaders + vertex input + output
state), then M spec-constant variants; K instanced`. Older builds print only
`N unique pipelines to build`. Builds from `d1c6119` on also log
`[ShaderPrecompile] vulkan driver: ...` and `backend = DXVK` on Windows.

## Installing

FusionFix is more than the `.asi`. If GTA IV does not already have FusionFix
installed, deploy the branch's `data\plugins\` **and** `data\update\` into the game
folder first, then overwrite the `.asi` with this one.

If FusionFix **is** already installed, only two files need to change:

```
<game>\plugins\GTAIV.EFLC.FusionFix.asi              <- this build
<game>\plugins\FusionFix.pipelinecache.baseline.bin  <- from cache\linux-amd-dxvk\
```

The `.ini` here is a **template**, not something to copy blindly: overwriting an
existing one discards whatever settings that install already has. Copy it only if
there is no `.ini` yet; otherwise just make sure these keys read:

```
PrecompileShaders = 1        (0 for a clean coverage capture -- see CLAUDE.md step 8)
CaptureDrawKeys = 1
PrecompileReplayCapturedKeys = 1
PrecompileExportBaseline = 0
```

## Why this build and not a release

There is no release. This work is not upstream and is not going upstream without the
owner's say-so, so the branch is the only source of truth and this binary is a
convenience copy of one commit on it.
