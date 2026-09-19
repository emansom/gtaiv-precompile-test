# Windows shader-directory result + a provenance mislabel to fix

Run 1 (the shader-cache run) on the Windows side, 2026-09-19.

## Answer to the question this session exists for

**Convergence holds.** Windows resolves the same shader directory as Linux, and the
Linux-captured baseline replays on Windows with nothing missing.

```
[ShaderCapture]   shader directory in use: win32_30
[ShaderPrecompile] replay: drew 2001 of 2001 pipelines in 35s
                   (skipped 0 duplicate-state, 0 no-shader, 0 no-decl, 0 no-RT)
```

`no-shader = 0 of 2001` is the independent tell HANDOFF.md asked for, and it is the
same 0 as Linux. Every shader the shipped baseline names exists on this install.

One golden cache is achievable across these two machines.

## Measured on

```
GPU     AMD Radeon RX 9070 XT   Windows driver 32.0.31035.1003 (Adrenalin)
Vulkan  AMD proprietary driver 2.0.395   <-- NOT RADV; this is the axis that differs
CPU     Ryzen 5 7600
OS      Windows 11 Home 25H2 build 26200.9457
DXVK    v3.1.1 (latest release, published 2026-09-15)
GPL     VK_EXT_graphics_pipeline_library SUPPORTED
ASI     shader-precompile-cache @ 9eb5766, sha256 4de01c78...a420 (branch head, not stale)
```

Note this is **not** the Windows+NVIDIA case HANDOFF.md anticipated — same GPU model
as the Linux rig, but the Vulkan driver differs (AMD proprietary 2.0.395 vs RADV
GFX1201). That still exercises the depth-format probe against a different
implementation, which is the mechanism that mattered; it does not answer the NVIDIA
question, which is still open.

## cacheinfo.py of the capture

```
container v1, 5 sections
  meta     offset 96              119 bytes       1 items
  rsTypes  offset 215             232 bytes      58 items
  decls    offset 447            1628 bytes      29 items
  keys     offset 2075        1173440 bytes    3667 items
  shaders  offset 1175515     1508868 bytes     542 items
shaderDir: win32_30
adapter:   AMD Radeon RX 9070 XT
driver:    32767.65535.65535.65535
os:        windows
config:    fmt=21 msaa=0  backend=native D3D9  vendor=0x1002 device=0x7550
captured:  67302 frames, 293708530 draws
```

Same `fmt=21 msaa=0` bucket as the Linux capture, so the two are directly comparable.

## MEASURED BUG: `backend` is recorded as "native D3D9" but the run was DXVK

The cache metadata and the log both say `backend native D3D9`. **That is wrong.**
DXVK v3.1.1 rendered this run. `backend` is provenance the merge tool buckets on, so
this needs fixing before Windows contributions are pooled, and any Windows cache
already collected should be treated as DXVK regardless of what its metadata says.

Evidence it was really DXVK, all from this launch:

- `GTAIV_d3d9.log` was rewritten at launch and contains `DXVK: v3.1.1`,
  `Graphics pipeline libraries supported`, and a created swapchain
  (`VK_FORMAT_B8G8R8A8_UNORM`, 1920x1080, `VK_PRESENT_MODE_IMMEDIATE_KHR`).
- Its `Effective configuration:` block echoes the `dxvk.hud` line that was added to
  `dxvk.conf` minutes before this launch — so that log is this process, not a stale one.
- The recorded driver `32767.65535.65535.65535` is not a real driver version. The
  actual Windows AMD driver is `32.0.31035.1003`. The recorded value is DXVK's
  placeholder, i.e. the ASI read a DXVK adapter identifier while concluding "native".

Likely mechanism — worth confirming against the source:

FusionFix 5.x on Windows does **not** ship DXVK as `d3d9.dll`. It ships its own
wrapper as `d3d9.dll` (1,343,072 bytes, `FileDescription: GTAIV.EFLC.FusionFix`,
version 5.0.2, and containing none of the strings `DXVK`/`dxvk`/`Vulkan`/
`vkCreateInstance`), and ships **DXVK renamed to `vulkan.dll`** (7,856,142 bytes,
`CompanyName: DXVK`, `FileDescription: Direct3D 9 Runtime`). The wrapper selects the
backend from `d3d9.cfg` `API = 1` / `GTAIV.EFLC.FusionFix.cfg` `GraphicsAPI = 1`.

So a backend probe that looks for DXVK *in the `d3d9.dll` module* succeeds on Linux
(where DXVK really is `d3d9.dll`) and fails on Windows, where `d3d9.dll` is
FusionFix's own wrapper. That matches the symptom exactly: correct on Linux, "native"
on Windows, while DXVK-specific values still flow through into the same record.

Suggested detection that does not depend on the filename: DXVK answers
`CheckDeviceFormat` for `VK_FORMAT`-backed FourCCs and reports the
`32767.65535.65535.65535` driver placeholder; either is a more reliable tell than the
module name. Cheapest correct fix is probably to probe the loaded `vulkan.dll` module
as well as `d3d9.dll`.

## Second finding: shader count is 1706 here, 1734 on Linux

```
[ShaderPrecompile] parsed 103 effects, 1706 unique shaders, 1689 passes (errors 0)
```

`update\common\shaders\win32_30` holds 103 `.fxc` files on this install, which matches
the "103 effects" parse. HANDOFF.md quotes 1734 shaders in that same directory. The
28-shader gap is therefore **not** an episode or directory difference — both sides read
the same 103-effect directory. It is a difference in what counts as a unique shader.
Not chased further here; flagging it because `Verify-Precompiler.ps1` hardcodes
`-ExpectedShaders 1734` and 1706 only passes because of the +/-15% tolerance.

Confirmed on disk that the episodes do **not** carry their own shader directories:

```
102 fxc  common\shaders\win32_30          (+ _atidx10 _low_ati _nv6 _nv7 _nv8, 102 each)
103 fxc  update\common\shaders\win32_30
```

`TLAD\` and `TBoGT\` contain `common movies pc content.dat ...` and no `shaders\`
directory at all. So the episode changes which content is drawn, never which shaders
exist.

## Caveat on the capture's key set: wrong episode

The route was driven as **Niko in base GTA IV**, not Johnny in TLAD. The saves were
all present and byte-identical to `saves/profile/` both before and after the run — the
cause is that GTA IV only lists saves belonging to the episode you launched, and
`GTAIV.exe` was launched directly:

```
SGTA400  "Story Complete"              (IV)
SGTA401  "TBoGT - TBoGT Complete"      (TBoGT)
SGTA402  "Story Complete"              (IV, created on this machine)
SGTA412  "Story Complete"              (IV)
SGTA413  "TLAD - Angels In America"    (TLAD)   <-- the Johnny save
SGTA414  "TBoGT - TBoGT Complete"      (TBoGT)
```

So the 3667 keys in this capture are base-IV content. The two decisive results above
are unaffected (the shader directory is resolved at device-probe time, and the 2001
replayed pipelines come from the shipped baseline, not from the route). Only a
key-set *diff* against the Linux TLAD capture would be confounded. Worth a re-run
under TLAD + `SGTA413` if that diff is wanted.

Also worth adding to `saves/README.md`: installing the files is not sufficient, the
matching **episode** has to be launched for them to appear.
