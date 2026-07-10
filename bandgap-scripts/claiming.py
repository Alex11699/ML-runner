"""
Shared atomic claim/finalize helpers for structure files moving through the
pending -> in-progress -> completed/failed pipeline, under run_root:

    run_root/_structures_inprogress/
    run_root/_structures_completed/
    run_root/_structures_failed/

Used by both driver.py (sbatch submission, decoupled from execution) and
driver_local.py (direct srun, synchronous). Under sbatch, the driver process
exits right after submitting, so it CANNOT be the thing that moves a
structure to _structures_completed/_failed once the job finishes — that has
to happen from inside run_scf.py/run_bands.py themselves, which is why
finalize_structure() lives here rather than in either driver script.
"""
import os
import time
from pathlib import Path


def ensure_dirs(run_root: Path):
    inprogress = run_root / "_structures_inprogress"
    completed = run_root / "_structures_completed"
    failed = run_root / "_structures_failed"
    for d in (inprogress, completed, failed):
        d.mkdir(parents=True, exist_ok=True)
    return inprogress, completed, failed


def claim_structure(struct_file: Path, inprogress_dir: Path) -> Path | None:
    """
    Atomically move struct_file into inprogress_dir. Returns the new path on
    success, or None if something else claimed it first (FileNotFoundError)
    or the move otherwise failed.
    """
    dst = inprogress_dir / struct_file.name
    try:
        struct_file.rename(dst)
        return dst
    except FileNotFoundError:
        return None
    except OSError as e:
        print(f"Warning: could not claim {struct_file.name}: {e}")
        return None


def finalize_structure(struct_path: Path, run_root: Path, success: bool):
    """
    Move a claimed structure (currently in _structures_inprogress) to
    _structures_completed or _structures_failed. Safe to call even if the
    file has already been moved (e.g. by a concurrent process, or because
    this is being called a second time) — logs and returns rather than
    raising, since a finalize race is not itself an error worth crashing over.
    """
    inprogress, completed, failed = ensure_dirs(run_root)
    dest_dir = completed if success else failed
    src = inprogress / struct_path.name
    if not src.exists():
        # Already moved (e.g. by a previous attempt, or another process) —
        # nothing to do, not an error.
        return
    try:
        src.rename(dest_dir / struct_path.name)
    except OSError as e:
        print(f"Warning: could not finalize {struct_path.name} to {dest_dir}: {e}")


def reclaim_inprogress(inprogress_dir: Path, structures_dir: Path, stale_minutes: float | None):
    """
    Move files sitting in _structures_inprogress/ back to the pending pool.
    If stale_minutes is set, only reclaim files older than that threshold
    (safe alongside genuinely active claims). If None, reclaims everything.
    """
    now = time.time()
    reclaimed = []
    for f in inprogress_dir.glob("*"):
        if not f.is_file():
            continue
        age_minutes = (now - f.stat().st_mtime) / 60
        if stale_minutes is not None and age_minutes < stale_minutes:
            continue
        dst = structures_dir / f.name
        try:
            f.rename(dst)
            reclaimed.append(f.name)
        except OSError as e:
            print(f"Warning: could not reclaim {f.name}: {e}")
    if reclaimed:
        print(f"Reclaimed {len(reclaimed)} stale in-progress structure(s) back to pending: {reclaimed}")
    return reclaimed
