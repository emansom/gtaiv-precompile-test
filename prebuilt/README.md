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
commit  d8bfec0  "shaders: log the install's .fxc hash set"
built   MSVC 14.51 (x86, /MT) via msvc-wine, the same toolchain and Platform=Win32
        target the project's CI uses
sha256  5709cd450272047c0fcb1ce80c3c38bb067b79fa9a32efc4ec3ed9c51083050d
size    5,962,752 bytes
```

**The log opens with the install's shader set** (`[FxcHashes]`): the directory, the
effect and shader counts, and a digest of the whole set, then one line per effect.
Same digest means the same shaders. Report the summary line. Known digests:

| install | effects / shaders | digest |
|---|---|---|
| FusionFix **release** (the 2026-09-19 Windows install) | 103 / 1706 | `f2c08d89613d1628` |
| FusionFix **branch** build, stock | 103 / 1706 | `d67ef3a9d5d18e1c` |
| the Linux rig (branch + Liberty City Plates) | 107 / 1734 | `77d73fec1c9c658a` |

**Cache files from this build carry no game shader bytecode.** The game's own `.fxc`
shaders are resolved by hash from the install; only the shaders FusionFix builds at
runtime travel as bytecode. Warming is unchanged. A side effect worth knowing: the
replay's `no-shader` count means something again. It counts keys naming a game
shader this install does not have. With the shipped baseline on a FusionFix
**release** install, expect exactly **4**: the branch's newer `gta_radar` shader
`f680fa1f75e55654`. Expect 0 on a branch install.

**Caches from your other PCs** go in `<game>\plugins\pipelinecache\`, any file name
ending in `.bin`. The replay warms them, and with `CaptureDrawKeys = 1` they are
merged into this PC's own capture.

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

If that branch has moved past `d8bfec0`, this binary is **stale**. Build from source
or ask for a fresh one. A stale ASI is the worst failure mode here because everything
still appears to work; it would just be measuring the wrong build.

A quick in-game tell that this build (or newer) is the one loaded: the replay's
summary line reads `... N base identities first (shaders + vertex input + output
state), then M spec-constant variants; K instanced`. Older builds print only
`N unique pipelines to build`. From `567b3cb` on, capture also logs `cache carries
bytecode for N shaders; M more are resolved from the install's .fxc files`. Builds
from `d1c6119` on log `[ShaderPrecompile] vulkan driver: ...` and `backend = DXVK`
on Windows.

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
