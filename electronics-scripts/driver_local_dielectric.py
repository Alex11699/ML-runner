#!/usr/bin/env python
"""
Sequential, no-queue driver for the dielectric-constant workflow. Same
claim-by-name / never-move-structures logic as driver_local.py, single-stage
instead of two. Runs correctly regardless of invocation directory -- locates
sibling scripts via its own file location, so one master copy works from
anywhere; point --structures-dir/--run-root at each new calculation.

Usage:
    python driver_local_dielectric.py --structures-dir inputs/ \
        --run-root runs_dielectric/ --limit 5
"""
import argparse
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

from claiming import ensure_dirs, claim_structure, release_claim, reclaim_stale_claims

REQUIRED_ENV_VARS = ["ASE_VASP_COMMAND", "VASP_PP_PATH"]
SCRIPT_DIR = Path(__file__).resolve().parent


def env_check():
    missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
    if missing:
        print("Missing required environment variable(s): " + ", ".join(missing))
        print('  export VASP_PP_PATH=/path/to/potcars')
        print('  export ASE_VASP_COMMAND="srun -n $SLURM_NTASKS vasp_std"')
        sys.exit(1)
    if "SLURM_JOB_ID" not in os.environ:
        print("Warning: SLURM_JOB_ID not set — srun calls below may queue rather than "
              "run immediately. Continuing anyway in case this is intentional.")


def stage_status(struct_dir: Path) -> str | None:
    status_file = struct_dir / "dielectric" / "dielectric_result.json"
    if not status_file.exists():
        return None
    try:
        return json.loads(status_file.read_text()).get("status")
    except (json.JSONDecodeError, OSError):
        return None


def run_stage(struct_file: Path, run_root: Path, log_path: Path) -> bool:
    script_path = SCRIPT_DIR / "run_dielectric.py"
    cmd = [sys.executable, str(script_path), str(struct_file), str(run_root)]
    with open(log_path, "w") as log:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        log.write(proc.stdout)
        print(proc.stdout, end="")
    return proc.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--structures-dir", required=True, type=Path)
    ap.add_argument("--run-root", required=True, type=Path)
    ap.add_argument("--pattern", default="*.cif")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--stop-on-first-failure", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--reclaim-stale-minutes", type=float, default=None)
    ap.add_argument("--reclaim-all-claims", action="store_true")
    args = ap.parse_args()

    env_check()
    args.run_root.mkdir(parents=True, exist_ok=True)
    claims_dir = ensure_dirs(args.run_root)

    if args.reclaim_all_claims:
        reclaim_stale_claims(claims_dir, stale_minutes=None)
    elif args.reclaim_stale_minutes is not None:
        reclaim_stale_claims(claims_dir, stale_minutes=args.reclaim_stale_minutes)

    job_id = os.environ.get("SLURM_JOB_ID")
    tag = f"job{job_id}_pid{os.getpid()}" if job_id else f"pid{os.getpid()}"
    ledger_path = args.run_root / f"job_ledger_{tag}.json"
    ledger = {}
    n_processed = 0

    print(f"[{tag}] starting. Structures dir (never modified): {args.structures_dir}")

    while args.limit is None or n_processed < args.limit:
        candidates = sorted(args.structures_dir.glob(args.pattern))
        if not candidates:
            print(f"[{tag}] no structures found matching {args.pattern}.")
            break
        random.shuffle(candidates)

        struct_file = None
        name = None
        for cand in candidates:
            cand_name = cand.stem
            if not args.force and stage_status(args.run_root / cand_name) == "ok":
                continue
            if claim_structure(cand_name, claims_dir):
                struct_file, name = cand, cand_name
                break

        if struct_file is None:
            remaining = [c for c in candidates
                         if args.force or stage_status(args.run_root / c.stem) != "ok"]
            if not remaining:
                print(f"[{tag}] all structures completed.")
                break
            print(f"[{tag}] all remaining candidates currently claimed elsewhere — retrying.")
            time.sleep(1)
            continue

        struct_dir = args.run_root / name
        (struct_dir / "dielectric").mkdir(parents=True, exist_ok=True)

        entry = {"structure_file": str(struct_file), "claimed_by": tag}
        t0 = time.time()
        n_processed += 1
        print(f"\n=== [{tag}] ({n_processed}{f'/{args.limit}' if args.limit else ''}) {name}: dielectric ===")

        prior = None if args.force else stage_status(struct_dir)
        if prior == "ok":
            print(f"[{name}] already completed (resume) — skipping.")
            ok = True
            entry["status"] = "ok (resumed)"
        else:
            ok = run_stage(struct_file, args.run_root, struct_dir / "dielectric" / "driver_local.log")
            entry["status"] = "ok" if ok else "failed"

        release_claim(name, claims_dir)  # idempotent -- no-op if run_dielectric.py already released it

        entry["elapsed_seconds"] = round(time.time() - t0, 1)
        ledger[name] = entry
        with open(ledger_path, "w") as f:
            json.dump(ledger, f, indent=2)

        if not ok and args.stop_on_first_failure:
            print(f"\n[{tag}] Stopping: {name} failed and --stop-on-first-failure was set.")
            print(f"Check {struct_dir / 'dielectric' / 'driver_local.log'} for details.")
            sys.exit(1)

    n_ok = sum(1 for e in ledger.values() if str(e.get("status", "")).startswith("ok"))
    print(f"\n[{tag}] Done: {n_ok}/{n_processed} structures completed successfully this instance.")
    print(f"Ledger: {ledger_path}")


if __name__ == "__main__":
    main()
