# state/ — shared scratch between the Linux and Windows Claude Code instances

Two Claude Code instances work on this: one on Arch/Proton/AMD, one on Windows. They
cannot see each other's memory (Claude Code memory is per-machine, per-project-path),
so anything that has to survive the hop lives **here, in git**.

## How to use it

- One file per finding or session, named `<date>-<side>-<topic>.md`
  (e.g. `2026-09-19-windows-shaderdir.md`).
- Write conclusions and the evidence for them, not a narrative. The other side needs
  to act on it without having watched it happen.
- **Say what was measured and what was assumed.** The single most expensive mistake
  in this project so far was reporting a number produced by the wrong identity
  definition; it looked plausible three separate times before the control caught it.
- Pull before you write, push when you are done. Neither side is authoritative.

## What belongs here

- `cacheinfo.py` output for any capture (a few lines, always worth committing).
- Which shader directory the game resolved, and on what hardware/driver/backend.
- Anything that contradicts `HANDOFF.md` — that file is a snapshot and will go stale.

## What does not

- Raw cache files (megabytes) unless a specific one is being handed over deliberately.
- Logs in full. Quote the handful of lines that carry the finding.
- Anything from the upstream-bug question that looks like a draft issue or PR. That
  stays local until the owner says otherwise.
