<!--
  This file is the BODY of the pinned/stickied GitHub issue "Hardware Test
  Results". The repo owner creates it as issue #1 and pins it. Testers add their
  results as COMMENTS on this issue (they do NOT edit this body).
-->

# 📊 Hardware Test Results — GTA IV Shader Precompiler

This is the crowd-sourced results board for the **FusionFix launch-time shader
precompiler** for **Grand Theft Auto IV** (Complete Edition, **running the latest
DXVK**) on Windows.

**What we're verifying:** a Vulkan pipeline is built the *first time* the game draws
with a given shader + render-state combination, which causes **stutter** (isolated
frame-time spikes). The precompiler builds them all **at launch** instead. This board
collects, across many GPUs / drivers / CPUs, whether that actually **eliminates
the in-gameplay compile stutter** — measured objectively with PresentMon.

⚠️ **DXVK is required.** GTA IV chooses between six shader directories by probing
depth formats. Under native Direct3D 9 the vendor's driver answers that probe, so
different GPUs load *different shader bytecode* and results cannot be compared across
machines. Under DXVK, DXVK answers it. Please don't post a native-D3D9 result — it
measures something else. Also note whether `VK_EXT_graphics_pipeline_library` is
active (in your DXVK log): with it on, most of this stutter is already gone, and "no
spikes either way" is a valid, useful result rather than a failed run.

## How to run the test (≈15 minutes)

You need: Windows 10/11, GTA IV with the **latest DXVK** installed, the FusionFix
build with the precompiler, and either **Claude Code** (easiest — it drives the whole
thing) or PowerShell.

1. Get the harness: `git clone https://github.com/emansom/gtaiv-precompile-test`
   *(the owner will fill in the real URL)*.
2. Open the folder in **Claude Code on Windows** and say *"run the precompile
   test"* — it follows `CLAUDE.md` step by step (installs PresentMon, clears the
   shader cache, captures a precompile-OFF then precompile-ON run over the same
   short drive, analyzes them, and formats your result).
   *Manual alternative:* run `run\Invoke-PrecompileTest.ps1 -Phase all` in an
   **Administrator** PowerShell and follow the prompts. See `README.md`.
3. It produces `results\result.md`. **Post that as a comment below.**

## Post your result

Comment on THIS issue with the block the harness generated (`results\result.md`).
If you have the GitHub CLI, the harness can post it for you:
`gh issue comment <THIS_ISSUE_NUMBER> --body-file results\result.md`.

Please keep the schema below so results compare cleanly. Fill every field
(`n/a` if truly unknown). Example: see `results/examples/result.example.md` in
the repo.

```markdown
### GTA IV Shader-Precompile Result -- PASS/FAIL

| field | value |
|---|---|
| **Verdict** | **PASS ✅** or **FAIL ❌** |
| GPU | <model> -- driver `<driver version>` [NVIDIA/AMD/Intel] |
| CPU | <model> (<cores>C/<threads>T) |
| OS | Windows <edition> <displayver> (build <build>) |
| RAM | <NN> GB |
| FusionFix ASI | `<branch>` @ `<commit>` |
| Precompiler | verified -- <N> shaders, <M> pipelines in <T>s at launch |
| Route | <sec>s fixed drive, driver shader cache cleared before each run |
| Harness | gtaiv-precompile-test v1 |

**Frame-time A/B (precompile OFF cold-cache -> ON):**

| metric | OFF (cold) | ON |
|---|---:|---:|
| isolated compile-stutter spikes | <n> | <n> |
| in-gameplay compiles (~= spikes) | <n> | <n> |
| p99 frame time (ms) | <ms> | <ms> |
| p99.9 frame time (ms) | <ms> | <ms> |
| max frame time (ms) | <ms> | <ms> |
| total stutter time (ms) | <ms> | <ms> |
| median frame time (ms) | <ms> | <ms> |

<!-- schema: gtaiv-precompile-result/v1 -->
```

## How to read a result

- **PASS** = with the precompiler ON, the isolated compile-stutter spikes seen
  on the cold OFF run drop to ~0, and the p99.9 / max frame times collapse toward
  the median. That's the win.
- **FAIL** = spikes remained ON. Please include your GPU + driver — that's exactly
  the hardware we need to look at (a driver that doesn't cache the way we assume,
  or a shader/state the precompiler missed).
- **Precompiler "not verified"** = the ASI may not have loaded; the numbers are
  unreliable. Re-check the install (`Verify-Precompiler`), then re-post.

Thanks for testing! Every GPU/driver combination helps.
