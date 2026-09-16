"""
Lock-file-based claim/release for structures moving through a shared pool
under concurrent worker instances.

UNLIKE the earlier version of this module, structure files are NEVER moved.
They stay exactly where you put them (your inputs/ directory, matching your
vasp_runner.py convention) for the entire lifetime of a batch -- claiming and
releasing operate on small lock files under run_root/_claims/, keyed by
structure name, not on the actual input files.

This makes redos/continuation runs simple: "is this structure done" is
answered purely by checking its own output status file (scf_status.json /
gap_result.json / dielectric_result.json) under run_root/<name>/ -- never by
which directory the input file currently happens to sit in, because it only
ever sits in one place.

One consequence worth knowing: a structure whose last recorded status is
"failed" (not "ok") is NOT specially quarantined anymore -- the next batch
run will simply attempt it again, since only "ok" causes a skip. This is
what makes redos low-friction, but it does mean a structure that fails for a
persistent, non-transient reason will be retried every time you rerun the
batch, burning compute each time, until you either fix the underlying issue
or explicitly filter it out. If you'd rather failed structures require
deliberate action to retry, say so and this can be changed to skip on ANY
recorded status (not just "ok") unless --force is passed.
"""
import os
import time
from pathlib import Path


def ensure_dirs(run_root: Path):
    """Only one reserved directory now (vs three before) -- claims_dir for
    lock files. No completed/failed/inprogress directories at all, since
    nothing physically moves."""
    claims_dir = run_root / "_claims"
    claims_dir.mkdir(parents=True, exist_ok=True)
    return claims_dir


def claim_structure(name: str, claims_dir: Path) -> bool:
    """
    Atomically claim a structure by NAME. Returns True if this call claimed
    it, False if something else already holds the claim (another instance,
    or a stale claim from a previous run -- see reclaim_stale_claims).

    Uses exclusive file creation (O_CREAT | O_EXCL), the same atomicity
    guarantee os.rename gave the old move-based design, just without
    touching the actual structure file.
    """
    lock_path = claims_dir / f"{name}.lock"
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def release_claim(name: str, claims_dir: Path):
    """
    Release a claim (delete its lock file). Call this as the terminal step
    for a structure regardless of success or failure -- the actual outcome
    lives in that structure's own status JSON, not in whether a claim is
    held. Safe to call even if already released (e.g. by a previous partial
    run) -- no-ops rather than raising.
    """
    lock_path = claims_dir / f"{name}.lock"
    lock_path.unlink(missing_ok=True)


def reclaim_stale_claims(claims_dir: Path, stale_minutes: float | None):
    """
    Delete lock files for crash recovery: a worker that was killed (e.g. hit
    its walltime) mid-structure leaves its lock file behind forever
    otherwise, permanently blocking that structure from ever being reclaimed
    by anyone. If stale_minutes is set, only deletes locks older than that
    threshold (safe alongside genuinely active workers, whose locks will
    have a recent mtime). If None, deletes every lock unconditionally --
    only use that when you're certain nothing is currently running.
    """
    now = time.time()
    reclaimed = []
    for f in claims_dir.glob("*.lock"):
        age_minutes = (now - f.stat().st_mtime) / 60
        if stale_minutes is not None and age_minutes < stale_minutes:
            continue
        f.unlink(missing_ok=True)
        reclaimed.append(f.stem)
    if reclaimed:
        print(f"Reclaimed {len(reclaimed)} stale claim(s): {reclaimed}")
    return reclaimed
