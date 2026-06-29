import glob
import os
import argparse
import time
from ase.io.trajectory import Trajectory

#!/usr/bin/env python3
import ase.io
from mace.calculators.mace import MACECalculator # type: ignore
#from sevenn.sevennet_calculator import SevenNetCalculator # type: ignore
#from orb_models.forcefield import pretrained # type: ignore
#from orb_models.forcefield.calculator import ORBCalculator # type: ignore
#from chgnet.model.dynamics import CHGNetCalculator # type: ignore

# Main Program
parser = argparse.ArgumentParser(description='Script for running single point calculations on a set of structure files using the desired ML calculator.')

parser.add_argument('-i', '--inpf', nargs='*', type=str, required=True, help='Input .res file(s)')
parser.add_argument('-ow', '--overwrite', default=False, action='store_true', help='Overwrite if output file exists (default: False)')

args = parser.parse_args()

initT = time.time()

MACE_model_path = glob.glob('*.model')

# Setup desired ML calculator
device = "cuda"  # Use "cuda" for GPU acceleration

calculator = MACECalculator(MACE_model_path)
#calculator = SevenNetCalculator(model= '7net-0', device=device)
#orbff = pretrained.orb_v2(device=device) # or choose another model using ORB_PRETRAINED_MODELS[model_name]()
#calculator = ORBCalculator(orbff, device=device)
#calculator = CHGNetCalculator()
#from pet_mad.calculator import PETMADCalculator
#calculator = PETMADCalculator(version="latest", device=device)

# Create outputs directory if it does not exist
output_dir = "."
os.makedirs(output_dir, exist_ok=True)

# Process each input file
for inpf in args.inpf:
    print(f"Processing {inpf}...")

    if not os.path.isfile(inpf):
        print(f"File {inpf} does not exist. Skipping...")
        continue

    # Read input structure
    try:
        atoms = ase.io.read(inpf)
    except Exception as e:
        print(f"Failed to read {inpf}: {e}")
        continue

    seed = os.path.splitext(os.path.basename(inpf))[0]
    output_file = os.path.join(output_dir, f"{seed}_single_point.res")

    if os.path.exists(output_file) and not args.overwrite:
        print(f"Output file {output_file} exists. Use -ow to overwrite. Skipping...")
        continue

    # Attach the desired ML calculator
    atoms.calc = calculator

    # Perform single point calculation
    print(f"Calculating single point energy for {seed}...")
    try:
        Ep = atoms.get_total_energy()
        print(f"Single point calculation completed. Energy: {Ep:.6f} eV")
    except Exception as e:
        print(f"Single point calculation failed for {inpf}: {e}")
        continue

    atoms.info['energy'] = Ep
    atoms.info['name'] = inpf

    # Save the results
    myres = ase.io.res.Res(atoms)
    myres.energy = Ep
    myres.write_file(output_file, write_info=0, significant_figures=6)

print('Single point calculations finished, Total time: %.2f s' % (time.time() - initT))
