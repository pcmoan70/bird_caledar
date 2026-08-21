# Lessons

## Killing intelenv/uv-launched generation jobs (2026-06-28)
**Mistake:** Launched `python regen_flagged.py --codes rerswa8` and tracked the
PID from `$!`. Later "killed" that PID — but the job kept running and starved
the main batch (two 36 GB FLUX models → memory thrashing; the main batch's log
froze for ~2 h while I thought rerswa8 was dead).

**Why:** The intelenv `python.exe` is a *launcher* that spawns the real worker
as a `uv` child process and then exits. The PID from `$!` (or `nohup … &`) is
the launcher/bash shell, which is gone almost immediately. `kill <that-pid>`
does nothing to the actual worker.

**How to apply:** To stop a generation job, find the *real* worker by its large
working set / command line, not the launcher PID:
`Get-CimInstance Win32_Process -Filter "Name='python.exe'"` → sort by
`WorkingSetSize` (the FLUX worker is tens of GB) and check `CommandLine`. Kill
that PID's tree. After killing, verify memory is actually released and the other
job's log resumes writing before assuming success. Don't run two FLUX processes
on this box at once — they thrash.

## Wikimedia Commons downloads: keep them serial (2026-08-21)
**Mistake:** Started a 4-thread helper to speed up `fetch_vonwright.py`'s
~8 s/file Commons thumbnail downloads. Commons answered 429 (Retry-After 600)
for ~10 minutes, so both the helper and the main script lost files.

**Why:** Commons throttles per client; thumbnail renditions are rendered on
demand and are slow by design. Parallel fetches don't go faster, they get cut off.

**How to apply:** One request at a time with the polite sleep in `EX._get`, run
in the background and wait. If files are missing after a run, wait 10 min and
re-run the (idempotent) fetch; it skips what's on disk and rewrites the CSV.
