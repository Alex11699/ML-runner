#!/usr/bin/env python3
import sys
print(f"Using Python: {sys.executable}")
import ase.io
from ase.optimize import BFGS
import glob
import ase.spacegroup
import ase.spacegroup.symmetrize
from ase.spacegroup.symmetrize import check_symmetry
from ase.utils import atoms_to_spglib_cell
import spglib
from spglib import get_symmetry_dataset as spglib_get_symmetry_dataset

#from ase.spacegroup import spacegroup,get_spacegroup,symmetrize

import torch
import os
import argparse
import time
import os.path,glob
import ase.build
from subprocess import Popen,PIPE # as popen # check_output
from sys import stdout,version_info
from ase.filters import FrechetCellFilter
from ase.io.trajectory import Trajectory


def force_exceeded(optimizer, atoms, force_threshold=100):
    """Stop optimization if any force exceeds the threshold (eV/A)."""
    max_force = max(abs(atoms.get_forces()).flatten())
    if max_force > force_threshold:
        print(f"Optimization aborted: force exceeded {force_threshold} eV/A (actual: {max_force:.2f} eV/A)")
        optimizer.stop()  # Gracefully stop optimization



# Main Program
parser = argparse.ArgumentParser(description='Script for running geometry optimizations on a set of structure files using the MACE calculator.')

parser.add_argument('-i', '--inpf', nargs='*', type=str, required=True, help='Input .res file(s)')

parser.add_argument('-it','--itype', type=str,required=False, help='Input file type. Def: determined automatically from the extension.')
parser.add_argument('-fmax', '--force_tol', type=float, default=0.05, help='Force convergence criterion (default: 0.05 ev/A)')
parser.add_argument('-ow', '--overwrite', default=False, action='store_true', help='Overwrite if output file exists (default: False)')
parser.add_argument('-t', '--tol',type=float, default=1e-4,help="The symmetry tolerance.")
parser.add_argument('-ml', '--ml_method', type=str, required=True,
                    choices=['MACE', '7NET', 'ORB', 'CHGNET', 'M3GNET', 'PET-MAD', 'MATTERSIM'],
                    help="Machine learning model to use for calculations.")

args = parser.parse_args()

initT=time.time()

# Set ML calculator
calculator = None
#device = "cuda"  # Change to "cuda" for GPU acceleration
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Running optimisations on {device}")


if args.ml_method == "MACE":
    from mace.calculators.mace import MACECalculator
    MACE_model_path = glob.glob('*.model')
    if not MACE_model_path:
        raise FileNotFoundError("No MACE model file found in the current directory.")
    calculator = MACECalculator(model_path=MACE_model_path,device=device)

elif args.ml_method == "7NET":
    from sevenn.sevennet_calculator import SevenNetCalculator
    calculator = SevenNetCalculator(model= '7net-0', device=device)

elif args.ml_method == "ORB":
    from orb_models.forcefield import pretrained
    from orb_models.forcefield.calculator import ORBCalculator
    orbff = pretrained.orb_v2(device=device)
    calculator = ORBCalculator(orbff, device=device)
    
elif args.ml_method == "CHGNET":
    from chgnet.model.model import CHGNet
    from chgnet.model.dynamics import CHGNetCalculator
    calculator = CHGNetCalculator(use_device=device)

elif args.ml_method == "M3GNET":
    import matgl
    from matgl.ext.ase import MEGNetCalculator
    from matgl.models import MEGNet
    #potential = M3GNet.models.Potential()
    #pot = matgl.load_model("M3GNet-MP-2021.2.8-PES")
    pot=matgl.load_model("MEGNet-MP-2018.6.1-PES")
    calculator = MEGNetCalculator(potential=pot)

elif args.ml_method == "PET-MAD":
    from pet_mad.calculator import PETMADCalculator
    calculator = PETMADCalculator(version="latest", device=device)

elif args.ml_method == "MATTERSIM":
    from mattersim.forcefield import MatterSimCalculator
    #from mattersim.forcefield import pretrained
    calculator = MatterSimCalculator(device=device)

else:
    raise ValueError(f"Unknown ML method: {args.ml_method}")


# Create outputs directory if it does not exist
output_dir = "outputs"
unconverged_dir = "unconverged"
os.makedirs(output_dir, exist_ok=True)
os.makedirs(unconverged_dir, exist_ok=True)

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
    output_file = os.path.join(output_dir, f"{seed}.res")
    unconverged_output_file = os.path.join(unconverged_dir, f"{seed}.res")

    if os.path.exists(output_file) and not args.overwrite:
        print(f"Output file {output_file} exists. Use -ow to overwrite. Skipping...")
        continue

    # Attach the desired ML calculator
    atoms.calc = calculator

    # Perform geometry optimization
    print(f"Optimizing {seed}...")
    try:
        ecf = FrechetCellFilter(atoms)
        optimizer = BFGS(ecf)
        traj = Trajectory(f"{output_dir}/{seed}.traj", 'w', atoms)
        optimizer.attach(traj)
        optimizer.attach(force_exceeded, 1, optimizer, atoms, 100)
        optimizer.run(fmax=args.force_tol, steps=500)
        Ep = atoms.get_potential_energy()

        if optimizer.converged():
            print(f"Optimization converged. Energy: {Ep:.6f} eV")
            atoms.info['energy'] = Ep
            atoms.info['name'] = inpf

            # Ensure the final structure in the .traj file matches the .res file
            final_atoms = ase.io.read(f"{output_dir}/{seed}.traj", index='-1')
            if not final_atoms == atoms:
                print(f"Warning: The final structure in {seed}.traj does not match the structure written to {seed}.res")

            # Get the pressure from the stress tensor
            stress = atoms.get_stress()
            P = -1 * sum(stress[:3]) / 3 * 160.21766208  # Convert to GPa
            atoms.info['pressure'] = P

            # Symmetrize the structure
            dataset = ase.spacegroup.symmetrize.refine_symmetry(atoms, symprec=1e-5, verbose=False)
            SG = dataset.international
            atoms.info['spacegroup'] = SG
            atoms.info['times_found'] = 1
            atoms.info['name'] = seed

            print('%s: Ep= %.5f P= %.2f GPa SG= %s' % (inpf, Ep, P, atoms.info['spacegroup']))

            myres = ase.io.res.Res(atoms)
            myres.energy = Ep
            myres.write_file(output_file, write_info=0, significant_figures=6)  # works!
        else:
            raise RuntimeError("Optimization did not converge")

    except Exception as e:
        Ep = atoms.get_potential_energy()
        print(f"Optimization failed for {inpf}: {e}")
        atoms.info['energy'] = Ep
        atoms.info['name'] = inpf

        # Ensure the final structure in the .traj file matches the .res file
        final_atoms = ase.io.read(f"{output_dir}/{seed}.traj", index='-1')
        if not final_atoms == atoms:
            print(f"Warning: The final structure in {seed}.traj does not match the structure written to {seed}.res")

        # Get the pressure from the stress tensor
        stress = atoms.get_stress()
        P = -1 * sum(stress[:3]) / 3 * 160.21766208  # Convert to GPa
        atoms.info['pressure'] = P

        # Symmetrize the structure
        dataset = ase.spacegroup.symmetrize.refine_symmetry(atoms, symprec=1e-5, verbose=False)
        SG = dataset.international
        atoms.info['spacegroup'] = SG
        atoms.info['times_found'] = 1
        atoms.info['name'] = seed

        print('%s: Ep= %.5f P= %.2f GPa SG= %s' % (inpf, Ep, P, atoms.info['spacegroup']))

        # Write unconverged structure to separate directory
        myres = ase.io.res.Res(atoms)
        myres.energy = Ep
        myres.write_file(unconverged_output_file, write_info=0, significant_figures=6)

        # Move the .traj file to the unconverged directory
        traj_file = f"{output_dir}/{seed}.traj"
        if os.path.exists(traj_file):
            os.rename(traj_file, os.path.join(unconverged_dir, f"{seed}.traj"))

print('Optimisations finished, Total time: %.2f s'%(time.time()-initT))
