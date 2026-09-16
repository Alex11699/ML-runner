#!/usr/bin/env python
"""
Fill submit_worker.sh.template once and submit K copies concurrently —
K sbatch calls total, each an independent worker draining the shared
structure pool via driver_local.py's claim loop (see submit_worker.sh.template
for the reasoning).

Usage:
    python launch_workers.py --structures-dir structures/ --run-root runs/ \
        --n-workers 10

    python launch_workers.py ... --dry-run   # fill + print, don't submit
"""
import argparse
import subprocess
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--structures-dir", required=True, type=Path)
    ap.add_argument("--run-root", required=True, type=Path)
    ap.add_argument("--n-workers", type=int, required=True,
                     help="number of concurrent worker jobs to submit — each reserves a "
                          "full node for up to 48h against your account's core-hour budget "
                          "while running, so pick this based on that budget and desired turnaround")
    ap.add_argument("--template", default="submit_worker.sh.template",
                     help="worker job template to fill and submit — use "
                          "submit_worker_dielectric.sh.template for the dielectric workflow "
                          "(default: submit_worker.sh.template, the bandgap workflow)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    args.run_root.mkdir(parents=True, exist_ok=True)
    (args.run_root / "_worker_logs").mkdir(parents=True, exist_ok=True)

    code_dir = Path(__file__).resolve().parent
    template = Path(args.template)
    if not template.exists():
        print(f"Expected {template} in the current directory (same place as launch_workers.py itself).")
        return

    text = template.read_text()
    text = (text
            .replace("%CODE_DIR%", str(code_dir))
            .replace("%STRUCTURES_DIR%", str(args.structures_dir.resolve()))
            .replace("%RUN_ROOT%", str(args.run_root.resolve())))

    filled_script = args.run_root / "submit_worker.sh"
    filled_script.write_text(text)
    print(f"Filled worker script: {filled_script}")

    if args.dry_run:
        print(f"[dry-run] would submit {args.n_workers} copies of {filled_script}")
        return

    job_ids = []
    for i in range(args.n_workers):
        out = subprocess.run(["sbatch", "--parsable", str(filled_script)],
                              capture_output=True, text=True, check=True)
        job_id = out.stdout.strip()
        job_ids.append(job_id)
        print(f"  worker {i+1}/{args.n_workers}: job {job_id}")

    print(f"\nSubmitted {len(job_ids)} worker(s): {', '.join(job_ids)}")
    print("Check progress with: squeue -u $USER")
    print("If the pending pool isn't empty once all workers finish, just rerun this "
          "command again for another round — already-completed/failed structures "
          "won't be resubmitted (they're no longer in the pending pool).")


if __name__ == "__main__":
    main()
