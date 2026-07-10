#!/usr/bin/env python
"""
Sequential, no-queue driver for trialling the SCF -> bands workflow on a
semi-local CPU cluster via direct srun, inside an interactive allocation.

Supports running MULTIPLE INSTANCES of this script concurrently against the
SAME structures-dir / run-root, and supports clean restarts after a crash.

How this works:
  - Structures start in --structures-dir (the "pending pool").
  - Before working on a structure, an instance CLAIMS it by atomically
    renaming the file into run-root/_structures_inprogress/. os.rename is
    atomic on POSIX, so if two instances race for the same file, exactly
    one succeeds (confirmed by a 20-process stress test) and the other
    gets FileNotFoundError, which just means "someone else got it, move on".
  - On success the claimed file is moved to _structures_completed/.
  - On failure it's moved to _structures_failed/ (NOT deleted or retried
    automatically, so failures need a deliberate decision, not silent retry).
  - RESUME: if a structure's run_root/<name>/scf/scf_status.json or
    bands/gap_result.json already shows status "ok", that stage is skipped
    rather than rerun — this matters both for restarts after a crash and
    for reclaimed in-progress structures (see --reclaim-stale-minutes).

Typical usage (can be launched from several terminals/allocations at once):
    python driver_local.py --structures-dir structures/ --run-root runs/ \
        --limit 5

If a previous run crashed and left structures stuck in
run-root/_structures_inprogress/, either:
  --reclaim-stale-minutes 60   # only reclaim files claimed >60 min ago
                                # (safe even if other instances are still
                                # legitimately running on younger claims)
  --reclaim-inprogress         # reclaim EVERYTHING in _structures_inprogress
                                # regardless of age — only use this if you
                                # are certain no other instance is running
"""
import argparse
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

from claiming import ensure_dirs, claim_structure, finalize_structure, reclaim_inprogress


REQUIRED_ENV_VARS = ["ASE_VASP_COMMAND", "VASP_PP_PATH"]


def env_check():
    missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
    if missing:
        print("Missing required environment variable(s): " + ", ".join(missing))
        print("Example, inside your salloc session:")
        print('  export VASP_PP_PATH=/path/to/potcars')
        print('  export ASE_VASP_COMMAND="srun -n $SLURM_NTASKS vasp_std"')
        sys.exit(1)
    if "SLURM_JOB_ID" not in os.environ:
        print("Warning: SLURM_JOB_ID not set — you don't appear to be inside a "
              "salloc allocation. srun calls below may queue rather than run "
              "immediately. Continuing anyway in case this is intentional.")


def instance_tag() -> str:
    """Identifier for this driver instance, used to namespace its ledger file
    so concurrent instances don't clobber each other's job_ledger writes."""
    job_id = os.environ.get("SLURM_JOB_ID")
    return f"job{job_id}_pid{os.getpid()}" if job_id else f"pid{os.getpid()}"


def stage_status(struct_dir: Path, stage: str) -> str | None:
    """Return the recorded 'status' field for a stage, or None if no record exists."""
    status_file = (struct_dir / "scf" / "scf_status.json" if stage == "scf"
                    else struct_dir / "bands" / "gap_result.json")
    if not status_file.exists():
        return None
    try:
        return json.loads(status_file.read_text()).get("status")
    except (json.JSONDecodeError, OSError):
        return None


def run_stage(script: str, struct_file: Path, run_root: Path, log_path: Path) -> bool:
    cmd = [sys.executable, script, str(struct_file), str(run_root)]
    with open(log_path, "w") as log:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        log.write(proc.stdout)
        print(proc.stdout, end="")
    return proc.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--structures-dir", required=True, type=Path,
                     help="pending pool — files here get claimed and moved out as they're processed")
    ap.add_argument("--run-root", required=True, type=Path)
    ap.add_argument("--pattern", default="*.cif")
    ap.add_argument("--limit", type=int, default=None,
                     help="max structures THIS instance will process (not a global cap across instances)")
    ap.add_argument("--stop-on-first-failure", action="store_true")
    ap.add_argument("--force", action="store_true",
                     help="ignore existing scf_status.json/gap_result.json and rerun both stages anyway")
    ap.add_argument("--reclaim-stale-minutes", type=float, default=None,
                     help="at startup, move in-progress structures older than this many minutes "
                          "back to the pending pool (safe alongside other running instances)")
    ap.add_argument("--reclaim-inprogress", action="store_true",
                     help="at startup, move ALL in-progress structures back to the pending pool "
                          "regardless of age — only use this if you are certain no other instance "
                          "is currently running")
    args = ap.parse_args()

    env_check()

    args.run_root.mkdir(parents=True, exist_ok=True)
    inprogress_dir, completed_dir, failed_dir = ensure_dirs(args.run_root)

    if args.reclaim_inprogress:
        reclaim_inprogress(inprogress_dir, args.structures_dir, stale_minutes=None)
    elif args.reclaim_stale_minutes is not None:
        reclaim_inprogress(inprogress_dir, args.structures_dir, stale_minutes=args.reclaim_stale_minutes)

    tag = instance_tag()
    ledger_path = args.run_root / f"job_ledger_{tag}.json"
    ledger = {}
    n_processed = 0

    print(f"[{tag}] starting. Pending pool: {args.structures_dir}")

    while args.limit is None or n_processed < args.limit:
        candidates = list(args.structures_dir.glob(args.pattern))
        if not candidates:
            print(f"[{tag}] no more structures in pending pool.")
            break
        random.shuffle(candidates)  # reduces contention when several instances start together

        claimed_path = None
        for cand in candidates:
            claimed_path = claim_structure(cand, inprogress_dir)
            if claimed_path is not None:
                break

        if claimed_path is None:
            print(f"[{tag}] lost the race on every visible candidate this pass — retrying.")
            time.sleep(1)
            continue

        name = claimed_path.stem
        struct_dir = args.run_root / name
        (struct_dir / "scf").mkdir(parents=True, exist_ok=True)
        (struct_dir / "bands").mkdir(parents=True, exist_ok=True)

        entry = {"structure_file": str(claimed_path), "claimed_by": tag}
        t0 = time.time()
        n_processed += 1
        print(f"\n=== [{tag}] ({n_processed}{f'/{args.limit}' if args.limit else ''}) {name}: SCF ===")

        scf_prior = None if args.force else stage_status(struct_dir, "scf")
        if scf_prior == "ok":
            print(f"[{name}] SCF already completed (resume) — skipping.")
            scf_ok = True
            entry["scf_status"] = "ok (resumed)"
        else:
            scf_ok = run_stage("run_scf.py", claimed_path, args.run_root,
                                struct_dir / "scf" / "driver_local.log")
            entry["scf_status"] = "ok" if scf_ok else "failed"

        bands_ok = False
        if scf_ok:
            bands_prior = None if args.force else stage_status(struct_dir, "bands")
            if bands_prior == "ok":
                print(f"[{name}] bands already completed (resume) — skipping.")
                bands_ok = True
                entry["bands_status"] = "ok (resumed)"
            else:
                print(f"=== [{tag}] {name}: bands ===")
                bands_ok = run_stage("run_bands.py", claimed_path, args.run_root,
                                      struct_dir / "bands" / "driver_local.log")
                entry["bands_status"] = "ok" if bands_ok else "failed"
        else:
            entry["bands_status"] = "skipped"

        # run_scf.py/run_bands.py finalize (move to completed/failed) themselves
        # on any path that actually executes. The one gap is a FULL resume
        # (both stages already "ok", so neither script ran this time) — call
        # finalize here too; it's idempotent and no-ops if already moved.
        finalize_structure(claimed_path, args.run_root, success=(scf_ok and bands_ok))

        entry["elapsed_seconds"] = round(time.time() - t0, 1)
        ledger[name] = entry
        with open(ledger_path, "w") as f:
            json.dump(ledger, f, indent=2)

        if not (scf_ok and bands_ok) and args.stop_on_first_failure:
            print(f"\n[{tag}] Stopping: {name} failed and --stop-on-first-failure was set.")
            print(f"Check {struct_dir / 'scf' / 'driver_local.log'} or "
                  f"{struct_dir / 'bands' / 'driver_local.log'} for details.")
            sys.exit(1)

    n_ok = sum(1 for e in ledger.values() if e.get("bands_status", "").startswith("ok"))
    print(f"\n[{tag}] Done: {n_ok}/{n_processed} structures completed SCF+bands successfully this instance.")
    print(f"Ledger: {ledger_path}")
    print("Run collect_results.py against the run-root once all instances have finished (or to check progress).")


if __name__ == "__main__":
    main()

