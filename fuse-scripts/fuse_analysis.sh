find . -name "global_minimum.cif" | python -c "
import sys
import re
from ase.io import read
from ase.formula import Formula
import spglib

for line in sys.stdin:
    f = line.strip()
    dirpath = '/'.join(f.split('/')[:-1])
    path = '/'.join(f.split('/')[-4:-1])  # exclude filename, show 3 dir levels

    # Space group and formula
    atoms = read(f)
    cell = (atoms.get_cell(), atoms.get_scaled_positions(), atoms.get_atomic_numbers())
    sg = spglib.get_spacegroup(cell, symprec=1e-1)
    formula = Formula(atoms.get_chemical_formula()).reduce()[0]

    # Energy from slurm file
    import glob
    energy = 'N/A'
    slurm_files = glob.glob(f'{dirpath}/slurm-*.out')
    for sf in slurm_files:
        with open(sf) as fh:
            for sl in fh:
                m = re.search(r'Lowest energy structure is: \d+ with energy: ([-\d.]+) eV/atom', sl)
                if m:
                    energy = f'{m.group(1)} eV/atom'

    print(f'{path} | {formula} | {sg} | {energy}')
"
