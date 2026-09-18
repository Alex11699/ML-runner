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

DEFAULT RETRY BEHAVIOR (changed 2026-09): a structure whose last recorded
status is anything other than "ok" (failed, gap_extraction_failed,
extraction_failed) is now skipped on subsequent batch runs by default, same
as a successful one -- not silently re-attempted. This was the earlier
behavior's known failure mode: with only "ok" causing a skip, a structure
that fails for a persistent, non-transient reason (a genuinely bad CSP
geometry, a systematic convergence issue) got reclaimed and re-run by
whichever worker in the pool next became free, indefinitely, for the rest
of the walltime -- confirmed in practice: 13/14 structures completing in
~250s each, the pool spending the remaining 18+ hours alternating retries
of the one structure that fails deterministically, with the workers never
exiting because the "pending pool" never actually empties.

Each driver script (driver.py / driver_local.py / driver_local_origcell.py /
driver_local_dielectric.py) now exposes:
  --retry-failed   opt back into re-attempting structures with a non-ok
                    status (but never "ok" ones) -- use after you've fixed
                    whatever caused the failure, or want to see if it was
                    transient.
  --max-retries N  (default 3) even under --retry-failed, a structure whose
                    recorded attempts (see write_status/read_status below)
                    reaches this cap is skipped anyway -- so a permanently-
                    broken structure can't reproduce the same walltime-
                    burning loop just because --retry-failed was passed.
  --force          unchanged: redo EVERYTHING regardless of recorded status,
                    including structures that already succeeded.
"""
import json
import os
import time
from pathlib import Path


def write_status(status_path: Path, status_dict: dict) -> dict:
    """
    Write a stage's status JSON (scf_status.json / gap_result.json /
    dielectric_result.json), stamping it with a cumulative "attempts" count:
    read from any prior file at this same path (0 if none, or unreadable),
    incremented by 1. This is what --max-retries checks against, so a
    structure that keeps failing under --retry-failed still eventually
    stops being reattempted rather than looping unboundedly. Returns the
    dict actually written (status_dict plus "attempts").
    """
    attempts = 0
    if status_path.exists():
        try:
            attempts = json.loads(status_path.read_text()).get("attempts", 0)
        except (json.JSONDecodeError, OSError):
            pass
    status_dict = dict(status_dict)
    status_dict["attempts"] = attempts + 1
    status_path.write_text(json.dumps(status_dict, indent=2))
    return status_dict


def read_status(status_path: Path) -> tuple[str | None, int]:
    """
    Companion to write_status(): returns (status, attempts) for a stage's
    status JSON -- (None, 0) if the file doesn't exist or can't be parsed
    (e.g. read mid-write). status is None for "never attempted", one of
    the stage's own status strings ("ok", "failed", ...) otherwise.
    """
    if not status_path.exists():
        return None, 0
    try:
        data = json.loads(status_path.read_text())
        return data.get("status"), data.get("attempts", 0)
    except (json.JSONDecodeError, OSError):
        return None, 0


def should_attempt(status_path: Path, args) -> bool:
    """
    The shared skip/attempt decision every driver's candidate loop uses.
    `args` needs .force, .retry_failed, .max_retries (all four driver
    scripts expose these identically). Returns True if this structure
    should be (re)attempted now.
    """
    if args.force:
        return True
    status, attempts = read_status(status_path)
    if status is None:
        return True  # never attempted
    if status == "ok":
        return False  # always skip successes
    if not args.retry_failed:
        return False  # new default: don't auto-retry a recorded failure
    return attempts < args.max_retries


def ensure_dirs(run_root: Path, stage: str | None = None):
    """
    Claims live under run_root/_claims -- or run_root/_claims/<stage>/ when
    `stage` is given. Pass `stage` ONLY for a workflow that's deliberately
    designed to share a run-root with another (currently: phonons, sharing
    with dielectric -- see run_phonons.py's docstring) -- otherwise leave
    it None (the default, unchanged behavior).

    WHY THIS MATTERS: claim_structure() below locks purely by structure
    NAME, with no notion of "which workflow" baked into claiming.py
    itself. Two workflows calling ensure_dirs(run_root) with the SAME
    run_root and no stage would share one flat claims directory, so
    claiming a structure for one workflow would ALSO block the other
    workflow's claim on that same-named structure -- they'd contend for
    the same lock despite being entirely independent stages. Bandgap and
    dielectric never hit this because they're never run against the same
    run-root (see config.py's module docstring); phonons IS run against
    the same run-root as dielectric, so it MUST pass a distinct stage
    here, at every call site that touches claims for it (both the driver
    and run_phonons.py's own release_claim() call at the end) -- a
    mismatch between those call sites' stage argument leaves a lock
    behind that a worker looks for it under the wrong directory to
    release.

    Only one reserved directory (vs three before the lock-file redesign)
    -- claims_dir for lock files. No completed/failed/inprogress
    directories at all, since nothing physically moves.
    """
    claims_dir = run_root / "_claims" if stage is None else run_root / "_claims" / stage
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
