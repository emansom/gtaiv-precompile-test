# Linux / AMD / DXVK reference caches

Captured on the machine this work was developed on, so a Windows run has something
real to compare against instead of starting from nothing.

| file | contents | what it is |
|---|---|---|
| `FusionFix.pipelinecache.baseline.bin` | 2001 pipelines, 29 decls, 525 shaders | the **shipped** baseline — what any player gets on first launch |
| `FusionFix.pipelinecache.f21-ms0.bin` | 14079 keys, 29 decls, 525 shaders | the full accumulated capture the baseline was distilled from |

Both report identical provenance:

```
shaderDir: win32_30
adapter:   AMD Radeon RX 9070 XT (RADV GFX1201)
os:        wine 11.0   backend: DXVK   vendor=0x1002 device=0x7550
config:    fmt=21 (D3DFMT_A8R8G8B8)  msaa=0
```

Run `python ..\..\tools\cache\cacheinfo.py <file>` to read that back from any
container, including one produced on Windows.

## Which one to deploy — deploy the BASELINE only

Copy `FusionFix.pipelinecache.baseline.bin` into `<game>\plugins\`. Do **not** also
copy the full capture, even though it is here.

The two warm almost exactly the same set (the baseline *is* the deduplication of that
capture, 2001 pipelines either way), so the full file buys no extra warming. What it
does cost is the ability to answer a question: if Windows starts from our capture and
records into it, the file that comes back is a mixture and "what did this machine see
on its own" can no longer be separated out. Starting from the baseline alone — which
is also what a real first-time player gets — leaves the Windows capture clean and
directly diffable against ours.

The full capture is here as reference: for inspecting, for diffing after the fact, and
in case a later run wants to pool deliberately rather than by accident.

## If Windows resolves a different shader directory

The capture will **refuse to merge** a cache whose `shaderDir` differs from the local
one and will say so in `FusionFix.shaders.log`:

```
<file> was captured against shader dir 'win32_30', this install uses '<other>' - not merging
```

That message is the **answer to the experiment**, not a failure to work around. It
means the golden cache has to be bucketed per shader directory. Leave the files in
place, note the line, and bring the log back — do not delete the baseline or try to
force the merge, because a forced union of two directories' keys is exactly the silent
corruption the check exists to prevent.
