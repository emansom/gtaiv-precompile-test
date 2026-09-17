### GTA IV Shader-Precompile Result -- PASS ✅

| field | value |
|---|---|
| **Verdict** | **PASS ✅** |
| GPU | NVIDIA GeForce RTX 4070 -- driver `32.0.15.6636` [NVIDIA] |
| CPU | AMD Ryzen 7 5800X3D (8C/16T) |
| OS | Windows 11 Pro 23H2 (build 22631.4169) |
| RAM | 32 GB |
| FusionFix ASI | `shader-precompile` @ `abc1234` |
| Precompiler | verified -- 1734 shaders, 2103 pipelines in 7.8 s at launch |
| Route | 90s fixed drive, driver shader cache cleared before each run |
| Harness | gtaiv-precompile-test v1 |

**Frame-time A/B (precompile OFF cold-cache -> ON):**

| metric | OFF (cold) | ON |
|---|---:|---:|
| isolated compile-stutter spikes | 12 | **0** |
| in-gameplay compiles (~= spikes) | 12 | **0** |
| p99 frame time (ms) | 25.1 | 24.7 |
| p99.9 frame time (ms) | 94.8 | 26.1 |
| max frame time (ms) | 227.2 | 27.1 |
| total stutter time (ms) | 1126 | 0 |
| median frame time (ms) | 16.78 | 16.76 |

<details><summary>run details</summary>

- frames OFF/ON: 5400 / 5400; duration 93.7s / 92.5s
- capture: PresentMon (present-to-present); source `presentmon`
- spike gate: excess>=8ms AND (dt>=1.5x baseline OR >5*MAD), window=61
- precompiler: 1734 shaders warmed at launch
- notes: cold-cache first-traversal baseline; downtown Algonquin loop

</details>

<!-- schema: gtaiv-precompile-result/v1 -->
