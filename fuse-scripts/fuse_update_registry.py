#!/usr/bin/env python3
# fuse_update_registry.py
# Updates registry rows with status=running, filling in results if complete
# Usage: python3 fuse_update_registry.py <registry.csv> <root_dir>

import csv, sys, os, re, glob
import spglib
from ase.io import read
from ase.formula import Formula

csv_path = sys.argv[1]
root_dir = sys.argv[2]

def get_slurm_status(dirpath, job_id):
    """Check slurm output for terminal status."""
    slurm_files = glob.glob(os.path.join(dirpath, f'slurm-{job_id}.out'))
    if not slurm_files:
        slurm_files = glob.glob(os.path.join(dirpath, 'slurm-*.out'))
    if not slurm_files:
        return 'running'

    with open(slurm_files[0]) as fh:
        lines = fh.readlines()

    # Check full file for traceback, last 50 lines for terminal status
    full_text = ''.join(lines)
    tail_text = ''.join(lines[-50:])

    if 'DUE TO TIME LIMIT' in tail_text:
        return 'timeout'
    if 'CANCELLED' in tail_text:
        return 'failed'
    if 'Traceback (most recent call last)' in full_text:
        return 'failed'
    if 'Error' in tail_text or 'error' in tail_text:
        return 'failed'
    if 'total time:' in tail_text:
        return 'no_cif'  # completed cleanly but no structure produced
    return 'running'


with open(csv_path) as f:
    rows = list(csv.DictReader(f))
    fieldnames = list(rows[0].keys())

updated = 0

for row in rows:
    if row['status'] != 'running':
        continue

    run_dir = os.path.join(root_dir, row['path'])

    if not os.path.isdir(run_dir):
        print(f"  WARNING: directory not found: {row['path']}")
        continue

    cif = os.path.join(run_dir, 'global_minimum.cif')

    if not os.path.exists(cif):
        slurm_status = get_slurm_status(run_dir, row['slurm_job_id'])
        if slurm_status != 'running':
            row['status'] = slurm_status
            print(f"  {slurm_status}: {row['path']}")
            updated += 1
        else:
            print(f"  still running: {row['path']}")
        continue

    # Has cif - extract results
    slurm_status = get_slurm_status(run_dir, row['slurm_job_id'])
    energy = time_taken = 'N/A'
    for sf in glob.glob(os.path.join(run_dir, 'slurm-*.out')):
        with open(sf) as fh:
            for line in fh:
                m = re.search(r'Lowest energy structure is: \d+ with energy: ([-\d.]+) eV/atom', line)
                if m:
                    energy = m.group(1)
                m = re.search(r'total time: (\d+:\d+:\d+)', line)
                if m:
                    time_taken = m.group(1)

    try:
        atoms = read(cif)
        cell = (atoms.get_cell(), atoms.get_scaled_positions(), atoms.get_atomic_numbers())
        sg = spglib.get_spacegroup(cell, symprec=1e-1)
        formula = str(Formula(atoms.get_chemical_formula()).reduce()[0])
    except Exception as e:
        print(f"  WARNING: could not read {cif}: {e}")
        sg = formula = 'N/A'

    row['status']             = 'complete'
    row['energy_ev_per_atom'] = energy
    row['space_group']        = sg
    row['formula_reduced']    = formula
    row['time_taken']         = time_taken

    print(f"  complete: {row['path']} | {sg} | {energy} | {time_taken}")
    updated += 1

with open(csv_path, 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)

print(f"\nDone — {updated} rows updated in {csv_path}")
