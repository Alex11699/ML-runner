#!/usr/bin/env python3
import glob
import os
import argparse
import time
import torch
import ase.io
from ase.io.trajectory import Trajectory

# -------------------------------
# Argument parser
# -------------------------------
parser = argparse.ArgumentParser(
    description='Run single-point energy calculations using a chosen ML calculator.'
)
parser.add_argument(
    '-i', '--inpf', nargs='*', type=str, required=True,
    help='Input structure file(s), e.g., .res or .xyz'
)
parser.add_argument(
    '-ow', '--overwrite', default=False, action='store_true',
    help='Overwrite if output file exists (default: False)'
)
parser.add_argument(
    '-ml', '--ml_method', type=str, required=True,
    choices=['MACE', '7NET', 'ORB', 'CHGNET', 'M3GNET', 'PET-MAD', 'MATTERSIM'],
    help="Machine learning model to use for single-point calculations."
)

args = parser.parse_args()
initT = time.time()

# -------------------------------
# Setup ML calculator
# -------------------------------
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Running single-point calculations on {device}")

calculator = None

if args.ml_method == "MACE":
    from mace.calculators.mace import MACECalculator
    MACE_model_path = glob.glob('*.model')
    if not MACE_model_path:
        raise FileNotFoundError("No MACE model file found in the current directory.")
    calculator = MACECalculator(model_path=MACE_model_path, device=device)

elif args.ml_method == "7NET":
    from sevenn.sevennet_calculator import SevenNetCalculator
    calculator = SevenNetCalculator(model='7net-0', device=device)

elif args.ml_method == "ORB":
    from orb_models.forcefield import pretrained
    from orb_models.forcefield.calculator import ORBCalculator
    orbff = pretrained.orb_v2(device=device)
    calculator = ORBCalculator(orbff, device=device)

elif args.ml_method == "CHGNET":
    from chgnet.model.dynamics import CHGNetCalculator
    calculator = CHGNetCalculator(use_device=device)

elif args.ml_method == "M3GNET":
    import matgl
    from matgl.ext.ase import MEGNetCalculator
    pot = matgl.load_model("MEGNet-MP-2018.6.1-PES")
    calculator = MEGNetCalculator(potential=pot)

elif args.ml_method == "PET-MAD":
    from pet_mad.calculator import PETMADCalculator
    calculator = PETMADCalculator(version="latest", device=device)

elif args.ml_method == "MATTERSIM":
    from mattersim.forcefield import MatterSimCalculator
    calculator = MatterSimCalculator(device=device)

else:
    raise ValueError(f"Unknown ML method: {args.ml_method}")

# -------------------------------
# Run single-point calculations
# -------------------------------
output_dir = "."
os.makedirs(output_dir, exist_ok=True)

for inpf in args.inpf:
    print(f"Processing {inpf}...")

    if not os.path.isfile(inpf):
        print(f"File {inpf} does not exist. Skipping...")
        continue

    try:
        atoms = ase.io.read(inpf)
    except Exception as e:
        print(f"Failed to read {inpf}: {e}")
        continue

    seed = os.path.splitext(os.path.basename(inpf))[0]
    output_file = os.path.join(output_dir, f"{seed}.res")

    if os.path.exists(output_file) and not args.overwrite:
        print(f"Output file {output_file} exists. Use -ow to overwrite. Skipping...")
        continue

    atoms.calc = calculator

    print(f"Calculating single-point energy for {seed}...")
    try:
        Ep = atoms.get_potential_energy()
        print(f"Energy: {Ep:.6f} eV")
    except Exception as e:
        print(f"Single-point calculation failed for {inpf}: {e}")
        continue

    atoms.info['energy'] = Ep
    atoms.info['name'] = inpf

    myres = ase.io.res.Res(atoms)
    myres.energy = Ep
    myres.write_file(output_file, write_info=0, significant_figures=6)

print('Single-point calculations finished, Total time: %.2f s' % (time.time() - initT))

