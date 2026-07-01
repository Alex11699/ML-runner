#!/usr/bin/env python3
# fuse_collect_structs.py
# Collects global_minimum.cif files using registry for unified naming
# Usage: python3 fuse_collect_structs.py <registry.csv> [root_dir]
# Searches from root_dir (default: cwd), uses registry for naming

import sys, os, shutil, re
from ase.io import read
from ase.formula import Formula

csv_path = sys.argv[1]
root_dir = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
out_dir  = os.path.join(root_dir, 'collected_structures')
os.makedirs(out_dir, exist_ok=True)

# Build lookup: absolute_path -> run_label_unified
import csv
registry = {}
with open(csv_path) as f:
    reg_root = os.path.dirname(os.path.abspath(csv_path))
    for row in csv.DictReader(f):
        abs_path = os.path.join(reg_root, row['path'])
        registry[abs_path] = row

# Find all global_minimum.cif files under root_dir
found = []
for dirpath, dirnames, filenames in os.walk(root_dir):
    if 'global_minimum.cif' in filenames:
        found.append(os.path.join(dirpath, 'global_minimum.cif'))

found.sort()
skipped = []

for cif in found:
    run_dir = os.path.dirname(os.path.abspath(cif))
    row = registry.get(run_dir)

    if row is None:
        print(f"  WARNING: not in registry, skipping: {cif}")
        skipped.append(cif)
        continue

    stoich = row['stoich']
    algo   = row['algo']
    label  = row['run_label_unified']

    if label == '1':
        dest_name = f'{stoich}_{algo}.cif'
    else:
        dest_name = f'{stoich}_{algo}-{label}.cif'

    dest = os.path.join(out_dir, dest_name)

    if os.path.exists(dest):
        print(f"  EXISTS (skipping): {dest_name}")
        continue

    shutil.copy(cif, dest)
    # Append provenance
    with open(dest, 'a') as fh:
        fh.write(f'\n# source: {run_dir}\n')
    print(f"  {cif} -> {dest_name}")

if skipped:
    print(f"\nSkipped {len(skipped)} unregistered directories:")
    for s in skipped:
        print(f"  {s}")
