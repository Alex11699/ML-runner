#!/usr/bin/env python
"""
Driver for the IGZO SCF -> non-SCF bandgap validation workflow on a
scheduler-managed HPC (e.g. Sulis), using sbatch + job dependencies.

Structures live permanently in --structures-dir (never moved -- point it at
your inputs/ directory, matching your vasp_runner.py convention). For every
structure not already completed, this:
  1. Atomically claims the structure BY NAME (a lock file under
     run-root/_claims/, NOT a file move)
  2. Fills in submit_scf.sh.template and submit_bands.sh.template
  3. Submits the SCF job
  4. Submits the bands job with --dependency=afterok:<scf_jobid>
  5. Records job IDs to job_ledger.json

This only submits jobs — it does not wait for them. Because sbatch decouples
submission from execution, THIS SCRIPT CANNOT RELEASE A CLAIM ITSELF once
submitted (it's long gone by the time the jobs finish) — that happens from
inside run_scf.py (on SCF failure) and run_bands.py (on success or failure),
which are the processes that actually know the outcome. If submission
itself fails (not the VASP job — sbatch rejecting the call), this script
does release the claim immediately, since nothing else ever will.

Claiming makes this restart-safe: run driver.py again any time (e.g. after
some jobs are still queued/running, or after a batch partially completed)
and already-completed structures are skipped (checked via their own
gap_result.json, not file location) and already-claimed ones are skipped
too, so nothing gets double-submitted.

Usage:
    python driver.py --structures-dir inputs/ --run-root runs/

If a previous invocation was interrupted mid-submission and left lock files
behind despite never actually submitting anything, use:
    python driver.py ... --reclaim-stale-minutes 30
Only reclaim structures whose jobs have actually finished/failed/never
started — check squeue / job_ledger.json first if unsure, since reclaiming
something with a job still legitimately queued will submit a second,
duplicate job for it.
"""
import argparse
import json
import subprocess
from pathlib import Path

from claiming import ensure_dirs, claim_structure, release_claim, reclaim_stale_claims


def stage_status(struct_dir: Path) -> str | None:
    status_file = struct_dir / "bands" / "gap_result.json"
    if not status_file.exists():
        return None
    try:
        return json.loads(status_file.read_text()).get("status")
    except (json.JSONDecodeError, OSError):
        return None


def fill_template(template_path: Path, out_path: Path, struct_file: Path,
                   struct_dir: Path, run_root: Path, struct_name: str, code_dir: Path):
    text = template_path.read_text()
    text = (text
            .replace("%STRUCT_NAME%", struct_name)
            .replace("%STRUCT_FILE%", str(struct_file))
            .replace("%STRUCT_DIR%", str(struct_dir))
            .replace("%RUN_ROOT%", str(run_root))
            .replace("%CODE_DIR%", str(code_dir)))
    out_path.write_text(text)


def submit(script_path: Path, dependency_jobid: str = None) -> str:
    cmd = ["sbatch", "--parsable"]
    if dependency_jobid:
        cmd.append(f"--dependency=afterok:{dependency_jobid}")
    cmd.append(str(script_path))
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--structures-dir", required=True, type=Path,
                     help="where your structure files live -- never modified or moved")
    ap.add_argument("--run-root", required=True, type=Path)
    ap.add_argument("--pattern", default="*.cif")
    ap.add_argument("--dry-run", action="store_true",
                     help="claim, fill templates, and print sbatch commands without submitting")
    ap.add_argument("--force", action="store_true",
                     help="ignore existing gap_result.json and resubmit anyway")
    ap.add_argument("--reclaim-stale-minutes", type=float, default=None,
                     help="at startup, release lock files older than this many minutes -- "
                          "see module docstring for the caveat about jobs still legitimately queued")
    ap.add_argument("--reclaim-all-claims", action="store_true",
                     help="at startup, release ALL lock files regardless of age -- only "
                          "use this if you're certain nothing is queued/running")
    args = ap.parse_args()

    args.run_root.mkdir(parents=True, exist_ok=True)
    claims_dir = ensure_dirs(args.run_root)

    if args.reclaim_all_claims:
        reclaim_stale_claims(claims_dir, stale_minutes=None)
    elif args.reclaim_stale_minutes is not None:
        reclaim_stale_claims(claims_dir, stale_minutes=args.reclaim_stale_minutes)

    ledger = {}
    code_dir = Path(__file__).resolve().parent
    scf_template = code_dir / "submit_scf.sh.template"
    bands_template = code_dir / "submit_bands.sh.template"

    candidates = sorted(args.structures_dir.glob(args.pattern))
    if not candidates:
        print(f"No structures found matching {args.pattern} in {args.structures_dir}")
        return

    n_submitted = 0

    for struct_file in candidates:
        name = struct_file.stem
        struct_dir = args.run_root / name

        if not args.force and stage_status(struct_dir) == "ok":
            continue  # already completed, checked via its own gap_result.json

        if not claim_structure(name, claims_dir):
            continue  # already claimed (by a previous run of this driver, or another instance)

        struct_dir_scf = struct_dir / "scf"
        struct_dir_bands = struct_dir / "bands"
        struct_dir_scf.mkdir(parents=True, exist_ok=True)
        struct_dir_bands.mkdir(parents=True, exist_ok=True)

        scf_script = struct_dir / "submit_scf.sh"
        bands_script = struct_dir / "submit_bands.sh"

        fill_template(scf_template, scf_script, struct_file, struct_dir, args.run_root, name, code_dir)
        fill_template(bands_template, bands_script, struct_file, struct_dir, args.run_root, name, code_dir)

        entry = {"structure_file": str(struct_file)}

        if args.dry_run:
            print(f"[dry-run] would submit {scf_script} then {bands_script} (dependency)")
            ledger[name] = entry
            n_submitted += 1
            continue

        try:
            scf_jobid = submit(scf_script)
            bands_jobid = submit(bands_script, dependency_jobid=scf_jobid)
            entry.update({"scf_jobid": scf_jobid, "bands_jobid": bands_jobid, "status": "submitted"})
            print(f"[{name}] scf={scf_jobid} bands={bands_jobid} (afterok dependency)")
            n_submitted += 1
        except subprocess.CalledProcessError as e:
            entry.update({"status": "submit_failed", "error": e.stderr})
            print(f"[{name}] submission failed: {e.stderr}")
            # submission itself failed (not the VASP job) — nothing will ever
            # run to release this claim, so release it now
            release_claim(name, claims_dir)

        ledger[name] = entry

    with open(args.run_root / "job_ledger.json", "w") as f:
        json.dump(ledger, f, indent=2)

    print(f"\nSubmitted {n_submitted} structure(s) (skipped structures already completed or "
          f"claimed by a previous run). Ledger written to {args.run_root / 'job_ledger.json'}")


if __name__ == "__main__":
    main()
