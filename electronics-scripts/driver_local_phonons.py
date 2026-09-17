#!/usr/bin/env python
"""
Sequential, no-queue driver for the finite-displacement phonon dispersion
workflow (see common_phonons.py's docstring for why finite differences,
not DFPT-on-supercell). Same claim-by-name / never-move-structures logic
as driver_local.py/driver_local_dielectric.py, one claim per STRUCTURE
(not per displacement) -- run_phonons.py runs every displaced supercell
for a structure sequentially inside its own subprocess call, so a
structure's "one stage" here is genuinely several VASP invocations, not
one. This means a structure here takes roughly (n_displacements x) as
long as the equivalent dielectric/bandgap structure -- expect minutes to
tens of minutes per structure locally, not seconds, before this is worth
pushing to a real HPC job-packing setup (no Slurm worker-pool wiring
exists for this workflow yet -- launch_workers_dielectric-style scripts
would be the natural next step once this is validated against a real
structure, and per-displacement granularity is worth deciding
deliberately rather than copying the per-structure pattern blindly).

Requires phonopy in this environment (`pip install phonopy`) in addition
to everything driver_local_dielectric.py needs.

Runs correctly regardless of invocation directory -- locates sibling
scripts via its own file location, so one master copy works from
anywhere; point --structures-dir/--run-root at each new calculation.

RETRY BEHAVIOR (see claiming.py's module docstring for the full story): a
structure whose last recorded status is anything other than "ok" is, by
default, NOT reattempted on a later invocation -- it's treated as settled,
same as a success, so it stops being reclaimed. Use --retry-failed to opt
back into reattempting failures, capped by --max-retries. NOTE: because a
structure here is several VASP calls, "not ok" doesn't distinguish which
displacement(s) failed -- check the structure's phonons/driver_local.log
and phonons/disp-*/  subdirectories to see how far it got.

Usage:
    python driver_local_phonons.py --structures-dir inputs/ \
        --run-root runs_phonons/ --limit 5
"""
import argparse
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

from claiming import ensure_dirs, claim_structure, release_claim, reclaim_stale_claims, read_status, should_attempt
import config as _config

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


def status_path(struct_dir: Path) -> Path:
    return struct_dir / "phonons" / "phonons_result.json"


def run_stage(struct_file: Path, run_root: Path, log_path: Path) -> bool:
    script_path = SCRIPT_DIR / "run_phonons.py"
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
    ap.add_argument("--config", type=Path, default=SCRIPT_DIR / "config_phonons.json",
                     help="JSON config for the DFPT run -- see CONFIG_REFERENCE.md. "
                          "Def: config_phonons.json next to this script. Resolved "
                          "ONCE and frozen to run-root/config_used.json on first "
                          "submission for this run-root (see config.py).")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--stop-on-first-failure", action="store_true")
    ap.add_argument("--force", action="store_true",
                     help="ignore existing phonons_result.json and rerun anyway, "
                          "including structures that already succeeded")
    ap.add_argument("--retry-failed", action="store_true",
                     help="reattempt structures whose last recorded status was a "
                          "failure (but never ones that already succeeded), up to "
                          "--max-retries attempts (see claiming.py's module docstring)")
    ap.add_argument("--max-retries", type=int, default=3,
                     help="even under --retry-failed, stop reattempting a structure "
                          "once its recorded attempts reaches this many (def: 3)")
    ap.add_argument("--reclaim-stale-minutes", type=float, default=None)
    ap.add_argument("--reclaim-all-claims", action="store_true")
    args = ap.parse_args()

    env_check()
    _resolved, config_path = _config.resolve_and_freeze(
        _config.PHONON_CONFIG_FIELDS, args.config, args.run_root)
    os.environ["PHONON_CONFIG_PATH"] = str(config_path)
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
            sp = status_path(args.run_root / cand_name)
            if not should_attempt(sp, args):
                continue
            if claim_structure(cand_name, claims_dir):
                struct_file, name = cand, cand_name
                break

        if struct_file is None:
            remaining = [c for c in candidates
                         if should_attempt(status_path(args.run_root / c.stem), args)]
            if not remaining:
                n_ok = sum(1 for c in candidates
                           if read_status(status_path(args.run_root / c.stem))[0] == "ok")
                n_failed = len(candidates) - n_ok
                print(f"[{tag}] all structures settled: {n_ok} completed, "
                      f"{n_failed} permanently failed (not retried -- pass "
                      f"--retry-failed to reattempt those).")
                break
            print(f"[{tag}] all remaining candidates currently claimed elsewhere — retrying.")
            time.sleep(1)
            continue

        struct_dir = args.run_root / name
        (struct_dir / "phonons").mkdir(parents=True, exist_ok=True)
        sp = status_path(struct_dir)

        entry = {"structure_file": str(struct_file), "claimed_by": tag}
        t0 = time.time()
        n_processed += 1
        print(f"\n=== [{tag}] ({n_processed}{f'/{args.limit}' if args.limit else ''}) {name}: dielectric ===")

        prior_status, _ = read_status(sp)
        if prior_status == "ok" and not args.force:
            print(f"[{name}] already completed (resume) — skipping.")
            ok = True
            entry["status"] = "ok (resumed)"
        elif prior_status is not None and prior_status != "ok" and not should_attempt(sp, args):
            print(f"[{name}] previously failed ({prior_status}) and won't be retried "
                  f"(pass --retry-failed to reattempt, up to --max-retries).")
            ok = False
            entry["status"] = f"skipped (previously {prior_status})"
        else:
            ok = run_stage(struct_file, args.run_root, struct_dir / "phonons" / "driver_local.log")
            entry["status"] = "ok" if ok else "failed"

        release_claim(name, claims_dir)  # idempotent -- no-op if run_phonons.py already released it

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
