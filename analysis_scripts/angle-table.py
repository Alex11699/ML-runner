#!/usr/bin/env python3
import os
import re
import sys  # <--- CHANGE: Import sys to read command-line arguments
import numpy as np
import matplotlib.pyplot as plt
from adjustText import adjust_text

def extract_lattice_angles(file_path):
    """Extract lattice angles (α, β, γ) from a .res.txt file."""
    with open(file_path, 'r') as file:
        for line in file:
            if "(α, β, γ)" in line:
                match = re.search(r"\(α, β, γ\)\s*=\s*([\d.]+)°\s+([\d.]+)°\s+([\d.]+)°", line)
                if match:
                    return tuple(map(float, match.groups()))
    return None

def get_files_with_angles(directory):
    """Retrieve a dictionary of file names and their extracted lattice angles."""
    files_with_angles = {}
    for file_name in os.listdir(directory):
        if file_name.endswith('.res.txt'):
            file_path = os.path.join(directory, file_name)
            try:
                angles = extract_lattice_angles(file_path)
                if angles is not None:
                    files_with_angles[file_name] = angles
            except Exception as e:
                print(f"Error processing file {file_name}: {e}", file=sys.stderr)
    return files_with_angles

def rmse(a, b):
    """Calculate the Root Mean Square Error (RMSE) between two arrays."""
    return np.sqrt(np.mean((np.array(a) - np.array(b))**2))

# <--- CHANGE: Modified the function to accept a plot_mode flag and return the RMSE values
def plot_rmse_angles(dft_angles, ml_angles, method_name, plot_mode=True):
    """Plot a parity plot overlaying lattice angles α, β, and γ."""
    common_files = set(dft_angles.keys()).intersection(ml_angles.keys())
    if not common_files:
        print("No matching files between directories for lattice angles.", file=sys.stderr)
        return None

    dft_values = np.array([dft_angles[file] for file in common_files])
    ml_values = np.array([ml_angles[file] for file in common_files])

    # Calculate RMSE for each angle
    rmse_values = [rmse(dft_values[:, i], ml_values[:, i]) for i in range(3)]

    # If not in plot mode, just return the RMSE values
    if not plot_mode:
        return rmse_values

    # --- Plotting code remains the same ---
    colors = ['r', 'g', 'b']
    labels = ['α', 'β', 'γ']
    fig, ax = plt.subplots(figsize=(8, 8))

    for i in range(3):
        ax.scatter(dft_values[:, i], ml_values[:, i], c=colors[i], alpha=0.7, label=f'{labels[i]} (RMSE = {rmse_values[i]:.4f})')

    max_val = np.max([dft_values, ml_values])
    min_val = np.min([dft_values, ml_values])
    line = np.linspace(min_val, max_val, 100)
    ax.plot(line, line, linestyle=':', color='black')

    ax.set_title(f'Lattice Angle Comparison: {method_name} vs DFT', fontsize=22)
    ax.set_xlabel('DFT Lattice Angle (°)', fontsize=22)
    ax.set_ylabel(f'{method_name} Lattice Angle (°)', fontsize=22)
    ax.tick_params(axis='both', which='major', labelsize=18)

    ax.legend(fontsize=18)
    ax.grid(True)
    
    fig.savefig(f"RMSE_Lattice_Angles_{method_name}_vs_DFT.png", format="png")
    plt.show()
    
    return rmse_values

# <--- CHANGE: Updated main to handle the '--table' argument
def main():
    # Check if running in table mode (no plots)
    table_mode = '--table' in sys.argv

    dft_dir = '../DFT_outputs'
    ml_dir = 'outputs'
    method_name = os.path.basename(os.getcwd())

    dft_angles = get_files_with_angles(dft_dir)
    ml_angles = get_files_with_angles(ml_dir)

    # Plot and compare (or just get RMSE in table mode)
    rmse_values = plot_rmse_angles(dft_angles, ml_angles, method_name, plot_mode=not table_mode)

    # If in table mode, print the result in the required format
    if table_mode and rmse_values is not None:
        # Output: method_name    rmse_alpha    rmse_beta    rmse_gamma
        print(f"{method_name}\t{rmse_values[0]:.4f}\t{rmse_values[1]:.4f}\t{rmse_values[2]:.4f}")

if __name__ == "__main__":
    main()