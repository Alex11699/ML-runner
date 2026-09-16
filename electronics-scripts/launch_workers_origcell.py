#!/usr/bin/env python
"""
ONE-OFF TEST VARIANT of launch_workers.py -- fills
submit_worker_origcell.sh.template (fixed, not a --template choice like the
regular script has) and submits K copies concurrently, each an independent
worker draining the shared structure pool via driver_local_origcell.py's
claim loop. See common_origcell.py's docstring for what this test actually
changes.

Same config schema as the regular bandgap workflow (config_bandgap.json /
BANDGAP_CONFIG_FIELDS) -- this test isn't about ENCUT/functional, just the
k-path step, so there's nothing dielectric-vs-bandgap to detect here and no
--template flag (unlike launch_workers.py, which serves both workflows).

Usage:
    python launch_workers_origcell.py --structures-dir structures/ \
        --run-root runs_origcell/ --n-workers 10

    python launch_workers_origcell.py ... --dry-run   # fill + print, don't submit
"""
import argparse
import subprocess
from pathlib import Path

import config as _config


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--structures-dir", required=True, type=Path)
    ap.add_argument("--run-root", required=True, type=Path)
    ap.add_argument("--n-workers", type=int, required=True,
                     help="number of concurrent worker jobs to submit — each reserves a "
                          "full node for up to 24h against your account's core-hour budget "
                          "while running, so pick this based on that budget and desired turnaround")
    ap.add_argument("--config", type=Path, default=None,
                     help="JSON config for the batch -- see CONFIG_REFERENCE.md. "
                          "Def: config_bandgap.json next to this script (same schema "
                          "as the regular bandgap workflow -- this test doesn't add "
                          "any new fields). Resolved ONCE and frozen to "
                          "run-root/config_used.json on first submission for this "
                          "run-root (see config.py).")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    code_dir = Path(__file__).resolve().parent
    template = code_dir / "submit_worker_origcell.sh.template"
    if not template.exists():
        print(f"Expected {template} to exist (looked next to "
              f"launch_workers_origcell.py itself at {code_dir}).")
        return

    config_path = args.config if args.config is not None else code_dir / "config_bandgap.json"

    args.run_root.mkdir(parents=True, exist_ok=True)
    (args.run_root / "_worker_logs").mkdir(parents=True, exist_ok=True)
    # .resolve() here matters: submit_worker_origcell.sh.template does
    # `cd %CODE_DIR%` before invoking driver_local_origcell.py --config, so a
    # relative frozen path would resolve against electronics-scripts/
    # instead of wherever this command was actually run from.
    _resolved, frozen_config_path = _config.resolve_and_freeze(
        _config.BANDGAP_CONFIG_FIELDS, config_path, args.run_root.resolve())

    text = template.read_text()
    text = (text
            .replace("%CODE_DIR%", str(code_dir))
            .replace("%STRUCTURES_DIR%", str(args.structures_dir.resolve()))
            .replace("%RUN_ROOT%", str(args.run_root.resolve()))
            .replace("%CONFIG_PATH%", str(frozen_config_path)))

    filled_script = args.run_root / "submit_worker_origcell.sh"
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
