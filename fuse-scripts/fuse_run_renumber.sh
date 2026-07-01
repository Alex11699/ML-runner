#!/bin/bash
# bump_run_dirs.sh
# Renames algo run dirs (e.g. pso, pso-2) to continue from master numbering
# Usage: bump_run_dirs.sh <working_dir> <master_dir>
# Example: bump_run_dirs.sh . ../complete-runs

WORKING="${1:?Usage: $0 <working_dir> <master_dir>}"
MASTER="${2:?Usage: $0 <working_dir> <master_dir>}"

python3 -c "
import os, re, sys

working = sys.argv[1]
master  = sys.argv[2]

ALGOS = ('pso', 'rand', 'tpe')

def parse_dir(name):
    m = re.match(r'^(pso|rand|tpe)(?:-(\d+))?$', name)
    if not m:
        return None
    return m.group(1), int(m.group(2) or 1)

for stoich in sorted(os.listdir(working)):
    stoich_path = os.path.join(working, stoich)
    if not os.path.isdir(stoich_path):
        continue

    # Find master max per algo for this stoich
    master_stoich = os.path.join(master, stoich)
    master_max = {}
    if os.path.isdir(master_stoich):
        for d in os.listdir(master_stoich):
            parsed = parse_dir(d)
            if parsed:
                algo, n = parsed
                master_max[algo] = max(master_max.get(algo, 0), n)

    # Find local dirs per algo, sorted ascending
    local = {}
    for d in os.listdir(stoich_path):
        parsed = parse_dir(d)
        if parsed:
            algo, n = parsed
            local.setdefault(algo, []).append((n, d))

    for algo, runs in local.items():
        runs.sort()
        offset = master_max.get(algo, 0)
        if offset == 0:
            print(f'  {stoich}/{algo}: no master runs found, skipping')
            continue
        # Rename in reverse order to avoid clobbering e.g. pso->pso-3 before pso-2->pso-4
        for local_n, dirname in reversed(runs):
            dest_n = local_n + offset
            new_name = f'{algo}-{dest_n}'
            src = os.path.join(stoich_path, dirname)
            dst = os.path.join(stoich_path, new_name)
            print(f'  {stoich}/{dirname} -> {new_name}')
            os.rename(src, dst)
" "$WORKING" "$MASTER"
