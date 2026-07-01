#!/usr/bin/env python3
# fuse_build_registry.py
# Scans all FUSE run directories and builds a CSV registry
# Usage: python3 fuse_build_registry.py <root_dir> <output_csv>
# Example: python3 fuse_build_registry.py . fuse_registry.csv

import os, re, sys, csv, glob
from ase.io import read
from ase.formula import Formula
import spglib

root = sys.argv[1] if len(sys.argv) > 1 else '.'
output = sys.argv[2] if len(sys.argv) > 2 else 'fuse_registry.csv'

ALGO_PAT = re.compile(r'^(pso|rand|tpe)(?:-(s?\d+))?$')

def is_short_run(path):
    return 'short-run' in path or 'short_run' in path

def parse_algo_dir(name):
    """Returns (algo_base, run_label, is_short) or None."""
    m = ALGO_PAT.match(name)
    if not m:
        return None
    algo = m.group(1)
    suffix = m.group(2)  # could be None, '2', 's1', 's2' etc
    if suffix is None:
        run_label = '1'
    else:
        run_label = suffix  # keep as-is, s-prefix or plain number
    return algo, run_label

def get_slurm_info(dirpath):
    """Extract job ID, energy, and time from slurm output file."""
    job_id = energy = time_taken = 'N/A'
    slurm_files = glob.glob(os.path.join(dirpath, 'slurm-*.out'))
    for sf in slurm_files:
        # Job ID from filename
        m = re.search(r'slurm-(\d+)\.out', os.path.basename(sf))
        if m:
            job_id = m.group(1)
        with open(sf) as fh:
            for line in fh:
                # Energy
                m = re.search(r'Lowest energy structure is: \d+ with energy: ([-\d.]+) eV/atom', line)
                if m:
                    energy = m.group(1)
                # Time
                m = re.search(r'total time: (\d+:\d+:\d+)', line)
                if m:
                    time_taken = m.group(1)
    return job_id, energy, time_taken

def get_structure_info(dirpath):
    """Extract space group and formula from global_minimum.cif."""
    cif = os.path.join(dirpath, 'global_minimum.cif')
    if not os.path.exists(cif):
        return 'N/A', 'N/A', False
    atoms = read(cif)
    cell = (atoms.get_cell(), atoms.get_scaled_positions(), atoms.get_atomic_numbers())
    sg = spglib.get_spacegroup(cell, symprec=1e-1)
    formula = str(Formula(atoms.get_chemical_formula()).reduce()[0])
    return sg, formula, True

rows = []

for dirpath, dirnames, filenames in os.walk(root):
    dirname = os.path.basename(dirpath)
    parsed = parse_algo_dir(dirname)
    if not parsed:
        continue

    algo, run_label = parsed
    stoich_dir = os.path.dirname(dirpath)
    stoich = os.path.basename(stoich_dir)

    # Skip if parent doesn't look like a stoichiometry
    if not re.match(r'^In', stoich):
        continue

    run_type = 'short' if is_short_run(dirpath) else 'long'
    rel_path = os.path.relpath(dirpath, root)

    job_id, energy, time_taken = get_slurm_info(dirpath)
    sg, formula, has_cif = get_structure_info(dirpath)
    status = 'complete' if has_cif else 'no_cif'

    rows.append({
        'stoich':           stoich,
        'algo':             algo,
        'run_label':        run_label,
        'type':             run_type,
        'path':             rel_path,
        'status':           status,
        'slurm_job_id':     job_id,
        'energy_ev_per_atom': energy,
        'space_group':      sg,
        'formula_reduced':  formula,
        'time_taken':       time_taken,
    })

# Sort: stoich, algo, long before short, then run_label numerically
def sort_key(r):
    label = r['run_label'].lstrip('s')
    n = int(label) if label.isdigit() else 0
    return (r['stoich'], r['algo'], 0 if r['type'] == 'long' else 1, n)

rows.sort(key=sort_key)

fields = ['stoich','algo','run_label','type','path','status',
          'slurm_job_id','energy_ev_per_atom','space_group','formula_reduced','time_taken']

with open(output, 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)

print(f'Written {len(rows)} rows to {output}')
