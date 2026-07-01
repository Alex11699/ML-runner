#!/usr/bin/env python3
# fuse_assign_unified_labels.py
# Adds run_label_unified column to the registry CSV
# Usage: python3 fuse_assign_unified_labels.py <registry.csv>

import csv, sys, re
from collections import defaultdict

csv_path = sys.argv[1]

with open(csv_path) as f:
    rows = list(csv.DictReader(f))

# Group by (stoich, algo, type) and sort to assign unified numbers
long_groups  = defaultdict(list)
short_groups = defaultdict(list)

for i, row in enumerate(rows):
    key = (row['stoich'], row['algo'])
    label = row['run_label']
    # Extract numeric part for sorting (strip leading s if present)
    n = int(re.sub(r's', '', label)) if re.match(r's?\d+', label) else 0
    if row['type'] == 'long':
        long_groups[key].append((n, row['path'], i))
    else:
        short_groups[key].append((n, row['path'], i))

unified = {}  # row index -> unified label

for key in set(list(long_groups.keys()) + list(short_groups.keys())):
    # Long runs: sort by run number then path to break ties
    longs = sorted(long_groups.get(key, []), key=lambda x: (x[0], x[1]))
    for unified_n, (_, _, i) in enumerate(longs, start=1):
        unified[i] = str(unified_n)

    # Short runs: sort by run number then path
    shorts = sorted(short_groups.get(key, []), key=lambda x: (x[0], x[1]))
    for unified_n, (_, _, i) in enumerate(shorts, start=1):
        unified[i] = f's{unified_n}'

# Write updated CSV with new column after run_label
fields = list(rows[0].keys())
if 'run_label_unified' not in fields:
    idx = fields.index('run_label') + 1
    fields.insert(idx, 'run_label_unified')

for i, row in enumerate(rows):
    row['run_label_unified'] = unified.get(i, row['run_label'])

with open(csv_path, 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)

print(f"Done — run_label_unified added to {csv_path}")
