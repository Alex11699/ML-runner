#!/usr/bin/env python3
# fuse_rename_short_dirs.py
# Renames short-run algo directories to use unified s-prefixed labels
# Usage: python3 fuse_rename_short_dirs.py <registry.csv> <root_dir> [--dry-run]

import csv, sys, os, re

csv_path = sys.argv[1]
root_dir = sys.argv[2]
dry_run = '--dry-run' in sys.argv

with open(csv_path) as f:
    rows = list(csv.DictReader(f))

def label_to_dirname(algo, label):
    if label == '1':
        return algo
    return f'{algo}-{label}'

renames = []

for row in rows:
    if row['type'] != 'short':
        continue

    algo = row['algo']
    path = row['path']
    unified = row['run_label_unified']

    parts = path.split('/')
    current_name = parts[-1]
    stoich_path = '/'.join(parts[:-1])
    target_name = label_to_dirname(algo, unified)

    if current_name == target_name:
        continue

    renames.append((stoich_path, current_name, target_name))

# Reverse sort by current number within each stoich+algo to avoid clobbering
def sort_key(r):
    stoich_path, current, target = r
    m = re.search(r'(\d+)$', current)
    n = int(m.group(1)) if m else 0
    return (stoich_path, -n)

renames.sort(key=sort_key)

if not renames:
    print("Nothing to rename.")
    sys.exit(0)

print(f"{'DRY RUN — ' if dry_run else ''}Renaming {len(renames)} directories:\n")

errors = []
for stoich_path, current, target in renames:
    src = os.path.join(root_dir, stoich_path, current)
    dst = os.path.join(root_dir, stoich_path, target)
    print(f"  {stoich_path}/{current} -> {target}")
    if not dry_run:
        if not os.path.isdir(src):
            errors.append(f"NOT FOUND: {src}")
            continue
        if os.path.exists(dst):
            errors.append(f"TARGET EXISTS: {dst}")
            continue
        os.rename(src, dst)

if errors:
    print(f"\nErrors ({len(errors)}):")
    for e in errors:
        print(f"  {e}")
elif not dry_run:
    print("\nAll renames complete.")

if dry_run:
    print("\nDry run — no changes made. Re-run without --dry-run to apply.")
