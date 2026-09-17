#!/usr/bin/env python
"""
Sequential, no-queue driver for the SCF -> bands bandgap workflow. Structures
live permanently in --structures-dir (never moved -- same convention as your
vasp_runner.py: point it at your inputs/ directory and it stays put).
Concurrency safety comes from small lock files under run-root/_claims/, not
from moving the real structure files.

Runs correctly regardless of what directory you invoke it from, and
regardless of where --structures-dir/--run-root point -- it locates its own
sibling scripts (run_scf.py, run_bands.py) via its own file location, not
via the current working directory. So you can keep ONE master copy of this
whole gap_workflow directory and point every new calculation at it:

    python /path/to/master/gap_workflow/driver_local.py \
        --structures-dir /path/to/this/calc/inputs \
        --run-root /path/to/this/calc/runs

No need to copy any .py file into each calculation's own directory.

RETRY BEHAVIOR (see claiming.py's module docstring for the full story): a
structure whose last recorded status (SCF or bands) is anything other than
"ok" is, by default, NOT reattempted on a later invocation -- it's treated
as settled, same as a success, so it stops being reclaimed. This is what
stops a single persistently-failing structure from being retried by
whichever worker in the pool next frees up, indefinitely, for the rest of
the walltime (confirmed in practice: 13/14 structures done in ~250s each,
the pool then spending 18+ hours alternating retries of the 14th). Use
--retry-failed to opt back into reattempting failures, capped by
--max-retries so that doesn't reproduce the same loop.

Usage:
    python driver_local.py --structures-dir inputs/ --run-root runs/ --limit 5
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
SCRIPT_DIR = Path(__file__).resolve().parent  # the one master copy's own location


def env_check():
    missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
    if missing:
        print("Missing required environment variable(s): " + ", ".join(missing))
        print('  export VASP_PP_PATH=/path/to/potcars')
        print('  export ASE_VASP_COMMAND="srun -n $SLURM_NTASKS vasp_std"')
        sys.exit(1)
    if "SLURM_JOB_ID" not in os.environ:
        print("Warning: SLURM_JOB_ID not set — you don't appear to be inside a "
              "salloc/sbatch allocation. srun calls below may queue rather than "
              "run immediately. Continuing anyway in case this is intentional.")


def instance_tag() -> str:
    job_id = os.environ.get("SLURM_JOB_ID")
    return f"job{job_id}_pid{os.getpid()}" if job_id else f"pid{os.getpid()}"


def status_paths(struct_dir: Path):
    return struct_dir / "scf" / "scf_status.json", struct_dir / "bands" / "gap_result.json"


def structure_needs_attempt(struct_dir: Path, args) -> bool:
    """
    Top-level "is there anything left to do for this structure right now"
    check, used both to decide whether to claim a candidate and to detect
    pool exhaustion. A structure is settled (returns False) once bands is
    "ok", OR once whichever stage last failed is not going to be retried
    (SCF failing permanently blocks bands from ever running, so that alone
    settles the structure without needing to check bands at all).
    """
    if args.force:
        return True
    scf_path, bands_path = status_paths(struct_dir)
    scf_status, _ = read_status(scf_path)
    bands_status, _ = read_status(bands_path)
    if bands_status == "ok":
        return False
    if scf_status is not None and scf_status != "ok" and not should_attempt(scf_path, args):
        return False  # SCF permanently failed -- bands can never run
    if bands_status is not None and bands_status != "ok" and not should_attempt(bands_path, args):
        return False  # bands permanently failed
    return True


def run_stage(script_name: str, struct_file: Path, run_root: Path, log_path: Path) -> bool:
    # Resolved against SCRIPT_DIR (this file's own location), NOT the
    # current working directory -- this is what lets one master copy work
    # regardless of where you invoke driver_local.py from.
    script_path = SCRIPT_DIR / script_name
    cmd = [sys.executable, str(script_path), str(struct_file), str(run_root)]
    with open(log_path, "w") as log:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        log.write(proc.stdout)
        print(proc.stdout, end="")
    return proc.returncode == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--structures-dir", required=True, type=Path,
                     help="where your structure files live -- read-only as far as this "
                          "script is concerned, nothing is ever moved out of it")
    ap.add_argument("--run-root", required=True, type=Path)
    ap.add_argument("--pattern", default="*.cif")
    ap.add_argument("--config", type=Path, default=SCRIPT_DIR / "config_bandgap.json",
                     help="JSON config for both scf and bands stages -- see "
                          "CONFIG_REFERENCE.md. Def: config_bandgap.json next to "
                          "this script. Resolved ONCE and frozen to "
                          "run-root/config_used.json on first submission for "
                          "this run-root; later --config edits don't retroactively "
                          "change an already-started batch (see config.py). Sets "
                          "BANDGAP_CONFIG_PATH in this process's environment, "
                          "inherited by the run_scf.py/run_bands.py subprocesses "
                          "below.")
    ap.add_argument("--limit", type=int, default=None,
                     help="max structures THIS instance will process (not a global cap)")
    ap.add_argument("--stop-on-first-failure", action="store_true")
    ap.add_argument("--force", action="store_true",
                     help="ignore existing scf_status.json/gap_result.json and rerun "
                          "both stages anyway, including structures that already "
                          "succeeded -- see also --retry-failed for a narrower option")
    ap.add_argument("--retry-failed", action="store_true",
                     help="reattempt structures whose last recorded status was a "
                          "failure (but never ones that already succeeded), up to "
                          "--max-retries attempts. Without this, a structure that "
                          "failed is skipped on later invocations, same as a "
                          "success -- see claiming.py's module docstring for why "
                          "that's the default.")
    ap.add_argument("--max-retries", type=int, default=3,
                     help="even under --retry-failed, stop reattempting a structure "
                          "once its recorded attempts (this stage) reaches this many "
                          "(def: 3) -- keeps a permanently-broken structure from "
                          "reproducing the same walltime-burning loop")
    ap.add_argument("--reclaim-stale-minutes", type=float, default=None,
                     help="at startup, release lock files older than this many minutes, "
                          "left behind by a worker that was killed mid-structure")
    ap.add_argument("--reclaim-all-claims", action="store_true",
                     help="at startup, release ALL lock files regardless of age -- only "
                          "use this if you're certain no other instance is currently running")
    args = ap.parse_args()

    env_check()
    _resolved, config_path = _config.resolve_and_freeze(
        _config.BANDGAP_CONFIG_FIELDS, args.config, args.run_root)
    os.environ["BANDGAP_CONFIG_PATH"] = str(config_path)
    claims_dir = ensure_dirs(args.run_root)

    if args.reclaim_all_claims:
        reclaim_stale_claims(claims_dir, stale_minutes=None)
    elif args.reclaim_stale_minutes is not None:
        reclaim_stale_claims(claims_dir, stale_minutes=args.reclaim_stale_minutes)

    tag = instance_tag()
    ledger_path = args.run_root / f"job_ledger_{tag}.json"
    ledger = {}
    n_processed = 0

    print(f"[{tag}] starting. Structures dir (never modified): {args.structures_dir}")

    while args.limit is None or n_processed < args.limit:
        candidates = sorted(args.structures_dir.glob(args.pattern))
        if not candidates:
            print(f"[{tag}] no structures found matching {args.pattern}.")
            break
        random.shuffle(candidates)  # reduces contention when several instances start together

        struct_file = None
        name = None
        for cand in candidates:
            cand_name = cand.stem
            struct_dir = args.run_root / cand_name

            if not structure_needs_attempt(struct_dir, args):
                continue

            if claim_structure(cand_name, claims_dir):
                struct_file, name = cand, cand_name
                break
            # else: someone else holds this claim right now -- try the next candidate

        if struct_file is None:
            # Every candidate is either settled (done or permanently failed)
            # or currently claimed by someone else.
            remaining = [c for c in candidates
                         if structure_needs_attempt(args.run_root / c.stem, args)]
            if not remaining:
                n_ok_settled = sum(1 for c in candidates
                                    if read_status(status_paths(args.run_root / c.stem)[1])[0] == "ok")
                n_failed_settled = len(candidates) - n_ok_settled
                print(f"[{tag}] all structures settled: {n_ok_settled} completed, "
                      f"{n_failed_settled} permanently failed (not retried -- pass "
                      f"--retry-failed to reattempt those).")
                break
            print(f"[{tag}] all remaining candidates currently claimed elsewhere — retrying.")
            time.sleep(1)
            continue

        struct_dir = args.run_root / name
        (struct_dir / "scf").mkdir(parents=True, exist_ok=True)
        (struct_dir / "bands").mkdir(parents=True, exist_ok=True)
        scf_status_path, bands_status_path = status_paths(struct_dir)

        entry = {"structure_file": str(struct_file), "claimed_by": tag}
        t0 = time.time()
        n_processed += 1
        print(f"\n=== [{tag}] ({n_processed}{f'/{args.limit}' if args.limit else ''}) {name}: SCF ===")

        scf_status, _ = read_status(scf_status_path)
        if scf_status == "ok" and not args.force:
            print(f"[{name}] SCF already completed (resume) — skipping.")
            scf_ok = True
            entry["scf_status"] = "ok (resumed)"
        elif scf_status is not None and scf_status != "ok" and not should_attempt(scf_status_path, args):
            print(f"[{name}] SCF previously failed ({scf_status}) and won't be retried "
                  f"(pass --retry-failed to reattempt, up to --max-retries). "
                  f"Skipping bands too — it depends on SCF.")
            scf_ok = False
            entry["scf_status"] = f"skipped (previously {scf_status})"
        else:
            scf_ok = run_stage("run_scf.py", struct_file, args.run_root,
                                struct_dir / "scf" / "driver_local.log")
            entry["scf_status"] = "ok" if scf_ok else "failed"

        bands_ok = False
        if scf_ok:
            bands_status, _ = read_status(bands_status_path)
            if bands_status == "ok" and not args.force:
                print(f"[{name}] bands already completed (resume) — skipping.")
                bands_ok = True
                entry["bands_status"] = "ok (resumed)"
            elif bands_status is not None and bands_status != "ok" and not should_attempt(bands_status_path, args):
                print(f"[{name}] bands previously failed ({bands_status}) and won't be "
                      f"retried (pass --retry-failed to reattempt, up to --max-retries).")
                entry["bands_status"] = f"skipped (previously {bands_status})"
            else:
                print(f"=== [{tag}] {name}: bands ===")
                bands_ok = run_stage("run_bands.py", struct_file, args.run_root,
                                      struct_dir / "bands" / "driver_local.log")
                entry["bands_status"] = "ok" if bands_ok else "failed"
        else:
            entry["bands_status"] = "skipped"

        # run_scf.py/run_bands.py already release their own claim on any
        # path that actually executes; this covers the gaps (full resume,
        # or a permanent-failure skip — nothing executed this run) —
        # release_claim is idempotent.
        release_claim(name, claims_dir)

        entry["elapsed_seconds"] = round(time.time() - t0, 1)
        ledger[name] = entry
        with open(ledger_path, "w") as f:
            json.dump(ledger, f, indent=2)

        if not (scf_ok and bands_ok) and args.stop_on_first_failure:
            print(f"\n[{tag}] Stopping: {name} failed and --stop-on-first-failure was set.")
            print(f"Check {struct_dir / 'scf' / 'driver_local.log'} or "
                  f"{struct_dir / 'bands' / 'driver_local.log'} for details.")
            sys.exit(1)

    n_ok = sum(1 for e in ledger.values() if str(e.get("bands_status", "")).startswith("ok"))
    print(f"\n[{tag}] Done: {n_ok}/{n_processed} structures completed SCF+bands successfully this instance.")
    print(f"Ledger: {ledger_path}")


if __name__ == "__main__":
    main()
