#!/usr/bin/env python
"""
Fill a submit_worker*.sh.template once and submit K copies concurrently —
K sbatch calls total, each an independent worker draining the shared
structure pool via the matching driver_local*.py's claim loop. Serves all
three production workflows (bandgap/dielectric/phonons) via --template;
see submit_worker.sh.template for the job-packing reasoning shared by all
of them.

Usage:
    python launch_workers.py --structures-dir structures/ --run-root runs/ \
        --n-workers 10

    python launch_workers.py --structures-dir structures/ \
        --run-root runs_phonons/ --n-workers 10 \
        --template submit_worker_phonons.sh.template

    python launch_workers.py ... --dry-run   # fill + print, don't submit
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
                          "full node for up to 48h against your account's core-hour budget "
                          "while running, so pick this based on that budget and desired turnaround")
    ap.add_argument("--template", default="submit_worker.sh.template",
                     help="worker job template to fill and submit — use "
                          "submit_worker_dielectric.sh.template for the dielectric workflow, "
                          "submit_worker_phonons.sh.template for the finite-displacement "
                          "phonon workflow (default: submit_worker.sh.template, the bandgap "
                          "workflow)")
    ap.add_argument("--config", type=Path, default=None,
                     help="JSON config for the batch -- see CONFIG_REFERENCE.md. "
                          "Def: config_bandgap.json / config_dielectric.json / "
                          "config_phonons.json next to this script, matching whichever "
                          "--template you picked. Resolved ONCE and frozen to "
                          "run-root/config_used.json on first submission for this "
                          "run-root (see config.py).")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    code_dir = Path(__file__).resolve().parent
    template = Path(args.template)
    if not template.is_absolute():
        # Resolve against this script's own location (not the current working
        # directory), so this works when invoked from a clean structures/runs
        # working directory -- same convention as driver_local.py's SCRIPT_DIR.
        template = code_dir / template
    if not template.exists():
        print(f"Expected {template} to exist (looked next to launch_workers.py itself "
              f"at {code_dir}, or pass an absolute path via --template).")
        return

    # Field schema + default config template picked by name -- add a new
    # elif here (not a new launch_workers_<x>.py copy) for any FUTURE
    # workflow that follows this same one-worker-per-structure job-packing
    # pattern; that's what this dispatch exists for. (launch_workers_origcell.py
    # is a deliberate exception -- a one-off test variant, not a third
    # production workflow, see its own docstring for why it's separate.)
    if "dielectric" in template.name:
        fields, default_config_name = _config.DIELECTRIC_CONFIG_FIELDS, "config_dielectric.json"
    elif "phonons" in template.name:
        fields, default_config_name = _config.PHONON_CONFIG_FIELDS, "config_phonons.json"
    else:
        fields, default_config_name = _config.BANDGAP_CONFIG_FIELDS, "config_bandgap.json"
    config_path = args.config
    if config_path is None:
        config_path = code_dir / default_config_name

    args.run_root.mkdir(parents=True, exist_ok=True)
    (args.run_root / "_worker_logs").mkdir(parents=True, exist_ok=True)
    # .resolve() here matters: submit_worker.sh.template does `cd %CODE_DIR%`
    # before invoking driver_local.py --config, so a relative frozen path
    # would resolve against electronics-scripts/ instead of wherever this
    # command was actually run from.
    _resolved, frozen_config_path = _config.resolve_and_freeze(fields, config_path, args.run_root.resolve())

    text = template.read_text()
    text = (text
            .replace("%CODE_DIR%", str(code_dir))
            .replace("%STRUCTURES_DIR%", str(args.structures_dir.resolve()))
            .replace("%RUN_ROOT%", str(args.run_root.resolve()))
            .replace("%CONFIG_PATH%", str(frozen_config_path)))

    # Named after the template used (submit_worker_phonons.sh, etc.), not a
    # constant "submit_worker.sh" -- was constant here before, harmless as
    # long as each workflow gets its own run-root (which config_used.json's
    # freeze/verify already forces you to do), but confusing once there are
    # three workflows' filled scripts to tell apart at a glance.
    filled_script = args.run_root / template.name.replace(".template", "")
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
