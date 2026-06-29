import os
import numpy as np
import matplotlib.pyplot as plt
from ase.io import read

def extract_forces_from_traj(file_path):
    """Extract forces from a .traj file."""
    try:
        atoms = read(file_path)  # Read the last frame (optimized structure)
        return atoms.get_forces()  # Returns an (N_atoms, 3) array of forces
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return None

def extract_forces_from_vasp(file_path):
    """Extract forces from a VASP vasprun.xml file."""
    try:
        atoms = read(file_path)  # Read final structure from vasprun.xml
        return atoms.get_forces()
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return None

def get_dft_forces(directory):
    """Retrieve force data from vasprun.xml files in Converged/{species}/."""
    files_with_forces = {}
    converged_dir = os.path.join(directory, "Converged")
    if not os.path.exists(converged_dir):
        print(f"Error: Converged directory not found in {directory}")
        return files_with_forces
    
    for species in os.listdir(converged_dir):
        species_path = os.path.join(converged_dir, species, "vasprun.xml")
        if os.path.exists(species_path):
            forces = extract_forces_from_vasp(species_path)
            if forces is not None:
                files_with_forces[species] = forces
    return files_with_forces

def get_ml_forces(directory):
    """Retrieve force data from .traj files named by species in outputs/."""
    files_with_forces = {}
    for file_name in os.listdir(directory):
        if file_name.endswith(".traj"):
            species = file_name.replace(".traj", "")
            file_path = os.path.join(directory, file_name)
            forces = extract_forces_from_traj(file_path)
            if forces is not None:
                files_with_forces[species] = forces
    return files_with_forces

def normalize_forces(forces):
    """Normalize forces by subtracting the mean of each component."""
    return forces - np.mean(forces, axis=0)

def compute_force_rmse(dft_forces, ml_forces):
    """Compute the RMSE between two normalized force arrays."""
    return np.sqrt(np.mean((dft_forces - ml_forces) ** 2))

def plot_force_comparison(dft_forces_dict, ml_forces_dict):
    """Plot normalized DFT vs ML forces."""
    common_files = set(dft_forces_dict.keys()).intersection(ml_forces_dict.keys())
    if not common_files:
        print("No matching files found.")
        return

    dft_forces_all = []
    ml_forces_all = []
    for species in common_files:
        dft_forces = normalize_forces(dft_forces_dict[species]).flatten()
        ml_forces = normalize_forces(ml_forces_dict[species]).flatten()
        dft_forces_all.extend(dft_forces)
        ml_forces_all.extend(ml_forces)
    
    dft_forces_all = np.array(dft_forces_all)
    ml_forces_all = np.array(ml_forces_all)
    
    plt.figure(figsize=(8, 8))
    plt.scatter(dft_forces_all, ml_forces_all, c='blue', alpha=0.5, label='Data Points')
    
    # Plot ideal agreement line (y = x)
    force_range = max(abs(dft_forces_all).max(), abs(ml_forces_all).max())
    line = np.linspace(-force_range, force_range, 100)
    plt.plot(line, line, linestyle=':', color='red', label='Ideal Agreement')
    
    plt.xlabel('DFT Normalized Force (eV/Å)', fontsize=14)
    plt.ylabel('ML Normalized Force (eV/Å)', fontsize=14)
    plt.title('Force Comparison: DFT vs ML', fontsize=16)
    plt.legend()
    plt.grid(True)
    plt.savefig("Force_Comparison.pdf", format="pdf")
    plt.show()

def compare_forces(dft_forces_dict, ml_forces_dict):
    """Compare forces between DFT and ML methods and calculate RMSE."""
    common_files = set(dft_forces_dict.keys()).intersection(ml_forces_dict.keys())
    mismatches = []

    for species in common_files:
        dft_forces = normalize_forces(dft_forces_dict[species])
        ml_forces = normalize_forces(ml_forces_dict[species])

        if dft_forces.shape != ml_forces.shape:
            print(f"Shape mismatch in {species}: DFT = {dft_forces.shape}, ML = {ml_forces.shape}")
            continue

        rmse = compute_force_rmse(dft_forces, ml_forces)
        mismatches.append((species, rmse))

    if mismatches:
        print("Normalized Force Comparison Results (species, RMSE in eV/Å):")
        for species, rmse in mismatches:
            print(f"{species}: RMSE = {rmse:.6f} eV/Å")
    else:
        print("No force mismatches found.")

def main():
    dft_dir = '.'
    ml_dir = 'MACE_outputs/outputs'

    # Retrieve forces from both directories
    dft_forces = get_dft_forces(dft_dir)
    ml_forces = get_ml_forces(ml_dir)

    # Compare and analyze force mismatches
    compare_forces(dft_forces, ml_forces)
    
    # Plot the force comparison
    plot_force_comparison(dft_forces, ml_forces)

if __name__ == "__main__":
    main()
