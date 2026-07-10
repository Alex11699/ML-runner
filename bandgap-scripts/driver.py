#!/usr/bin/env python
"""
Driver for the IGZO SCF -> non-SCF bandgap validation workflow on a
scheduler-managed HPC (e.g. Sulis), using sbatch + job dependencies.

For every structure file in --structures-dir, this:
  1. Atomically CLAIMS the structure (moves it into run-root/_structures_inprogress/)
  2. Fills in submit_scf.sh.template and submit_bands.sh.template
  3. Submits the SCF job
  4. Submits the bands job with --dependency=afterok:<scf_jobid>
  5. Records job IDs to job_ledger.json

This only submits jobs — it does not wait for them. Because sbatch decouples
submission from execution, THIS SCRIPT CANNOT MOVE STRUCTURES TO
_structures_completed/_failed ITSELF (it's long gone by the time the jobs
finish) — that happens from inside run_scf.py (on SCF failure) and
run_bands.py (on success or failure), which are the processes that actually
know the outcome.

Claiming makes this restart-safe: if you run driver.py again (e.g. after
some jobs are still queued/running, or after a batch partially completed),
already-claimed/completed/failed structures are simply not in the pending
pool anymore, so nothing gets double-submitted.

Usage:
    python driver.py --structures-dir structures/ --run-root runs/

If a previous invocation was interrupted mid-submission (e.g. killed partway
through the structure loop) and left files stuck in _structures_inprogress
despite never actually being submitted, use:
    python driver.py ... --reclaim-stale-minutes 30
to move those back to the pending pool before resubmitting. Only reclaim
structures whose jobs have actually finished/failed/never started — check
squeue / job_ledger.json first if unsure, since reclaiming something with a
job still legitimately queued will submit a second, duplicate job for it.
"""
import argparse
import json
import subprocess
from pathlib import Path

from claiming import ensure_dirs, claim_structure, reclaim_inprogress


def fill_template(template_path: Path, out_path: Path, struct_file: Path,
                   struct_dir: Path, run_root: Path, struct_name: str):
    text = template_path.read_text()
    text = (text
            .replace("%STRUCT_NAME%", struct_name)
            .replace("%STRUCT_FILE%", str(struct_file))
            .replace("%STRUCT_DIR%", str(struct_dir))
            .replace("%RUN_ROOT%", str(run_root)))
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
                     help="pending pool — files here get claimed (moved out) as they're submitted")
    ap.add_argument("--run-root", required=True, type=Path,
                     help="output root, mirrors run_scf.py/run_bands.py's run_root arg")
    ap.add_argument("--pattern", default="*.cif",
                     help="glob pattern for structure files (default: *.cif)")
    ap.add_argument("--dry-run", action="store_true",
                     help="claim, fill templates, and print sbatch commands without submitting "
                          "(NOTE: this still claims — i.e. moves files out of the pending pool. "
                          "Use --reclaim-inprogress afterwards to undo a dry run.)")
    ap.add_argument("--reclaim-stale-minutes", type=float, default=None,
                     help="at startup, move in-progress structures older than this many minutes "
                          "back to the pending pool before submitting — see module docstring "
                          "for the caveat about jobs still legitimately queued")
    ap.add_argument("--reclaim-inprogress", action="store_true",
                     help="at startup, move ALL in-progress structures back to the pending pool "
                          "regardless of age — only use this if you're certain nothing is queued/running")
    args = ap.parse_args()

    args.run_root.mkdir(parents=True, exist_ok=True)
    inprogress_dir, completed_dir, failed_dir = ensure_dirs(args.run_root)

    if args.reclaim_inprogress:
        reclaim_inprogress(inprogress_dir, args.structures_dir, stale_minutes=None)
    elif args.reclaim_stale_minutes is not None:
        reclaim_inprogress(inprogress_dir, args.structures_dir, stale_minutes=args.reclaim_stale_minutes)

    ledger = {}
    scf_template = Path("submit_scf.sh.template")
    bands_template = Path("submit_bands.sh.template")

    candidates = sorted(args.structures_dir.glob(args.pattern))
    if not candidates:
        print(f"No structures found matching {args.pattern} in {args.structures_dir}")
        return

    n_submitted = 0
    for struct_file in candidates:
        claimed_path = claim_structure(struct_file, inprogress_dir)
        if claimed_path is None:
            continue  # already claimed by a previous run of this driver

        name = claimed_path.stem
        struct_dir = args.run_root / name
        (struct_dir / "scf").mkdir(parents=True, exist_ok=True)
        (struct_dir / "bands").mkdir(parents=True, exist_ok=True)

        scf_script = struct_dir / "submit_scf.sh"
        bands_script = struct_dir / "submit_bands.sh"

        fill_template(scf_template, scf_script, claimed_path, struct_dir, args.run_root, name)
        fill_template(bands_template, bands_script, claimed_path, struct_dir, args.run_root, name)

        entry = {"structure_file": str(claimed_path)}

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
            # run to finalize this one, so reclaim it to pending rather than
            # leaving it stuck in _structures_inprogress with no job behind it
            claimed_path.rename(args.structures_dir / claimed_path.name)

        ledger[name] = entry

    with open(args.run_root / "job_ledger.json", "w") as f:
        json.dump(ledger, f, indent=2)

    print(f"\nSubmitted {n_submitted} structure(s) (skipped structures already claimed by a "
          f"previous run). Ledger written to {args.run_root / 'job_ledger.json'}")


if __name__ == "__main__":
    main()
