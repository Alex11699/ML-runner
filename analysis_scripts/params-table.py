#!/usr/bin/env python3
import os
import re
import sys  # <--- CHANGE: Import sys to read command-line arguments
import numpy as np
import matplotlib.pyplot as plt
from adjustText import adjust_text

def extract_lattice_parameters(file_path):
    """Extract lattice parameters (a, b, c) from a .res.txt file."""
    with open(file_path, 'r') as file:
        for line in file:
            if "(a, b, c)" in line:
                match = re.search(r"\(a, b, c\)\s*=\s*([\d.]+) Å,\s*([\d.]+) Å,\s*([\d.]+) Å", line)
                if match:
                    return tuple(map(float, match.groups()))
    return None

def get_files_with_lattice(directory):
    """Retrieve a dictionary of file names and their extracted lattice parameters."""
    files_with_lattice = {}
    for file_name in os.listdir(directory):
        if file_name.endswith('.res.txt'):
            file_path = os.path.join(directory, file_name)
            try:
                lattice_params = extract_lattice_parameters(file_path)
                if lattice_params is not None:
                    files_with_lattice[file_name] = lattice_params
            except Exception as e:
                print(f"Error processing file {file_name}: {e}", file=sys.stderr)
    return files_with_lattice

def rmse(a, b):
    """Calculate the Root Mean Square Error (RMSE) between two arrays."""
    return np.sqrt(np.mean((np.array(a) - np.array(b))**2))

# <--- CHANGE: Modified the function to accept a plot_mode flag and return the RMSE values
def plot_rmse_lattice(dft_lattice, ml_lattice, method_name, plot_mode=True):
    """Plot a parity plot overlaying lattice parameters a, b, and c."""
    common_files = set(dft_lattice.keys()).intersection(ml_lattice.keys())
    if not common_files:
        print("No matching files between directories for lattice parameters.", file=sys.stderr)
        return None

    dft_values = np.array([dft_lattice[file] for file in common_files])
    ml_values = np.array([ml_lattice[file] for file in common_files])

    dft_normalized = dft_values - np.mean(dft_values, axis=0)
    ml_normalized = ml_values - np.mean(ml_values, axis=0)

    # Calculate RMSE for each parameter (a, b, c)
    rmse_values = [rmse(dft_normalized[:, i], ml_normalized[:, i]) for i in range(3)]

    # If not in plot mode, just return the RMSE values
    if not plot_mode:
        return rmse_values

    # --- Plotting code remains the same ---
    colors = ['r', 'g', 'b']
    labels = ['a', 'b', 'c']
    fig, ax = plt.subplots(figsize=(8, 8))

    for i in range(3):
        ax.scatter(dft_normalized[:, i], ml_normalized[:, i], c=colors[i], alpha=0.7, label=f'{labels[i]} (RMSE = {rmse_values[i]:.4f})')

    max_range = max(abs(dft_normalized).max(), abs(ml_normalized).max())
    line = np.linspace(-max_range, max_range, 100)
    ax.plot(line, line, linestyle=':', color='black')

    ax.set_title(f'Lattice Parameter Comparison: {method_name} vs DFT', fontsize=22)
    ax.set_xlabel('DFT Normalized Lattice Parameter (Å)', fontsize=22)
    ax.set_ylabel(f'{method_name} Normalized Lattice Parameter (Å)', fontsize=22)
    ax.tick_params(axis='both', which='major', labelsize=18)
    ax.legend(fontsize=18)
    ax.grid(True)

    # Note: Interactive on_click functionality is disabled in non-interactive environments
    # but is kept here for when the script is run normally.

    fig.savefig(f"RMSE_Lattice_{method_name}_vs_DFT.png", format="png")
    plt.show()
    
    return rmse_values

# <--- CHANGE: Updated main to handle the '--table' argument
def main():
    # Check if running in table mode (no plots)
    table_mode = '--table' in sys.argv

    dft_dir = '../DFT_outputs/original-uniq-structs-Converged/'
    ml_dir = './single-points'
    method_name = os.path.basename(os.getcwd())

    dft_lattice = get_files_with_lattice(dft_dir)
    ml_lattice = get_files_with_lattice(ml_dir)

    # Plot and compare (or just get RMSE in table mode)
    rmse_values = plot_rmse_lattice(dft_lattice, ml_lattice, method_name, plot_mode=not table_mode)

    # If in table mode, print the result in the required format
    if table_mode and rmse_values is not None:
        # Output: method_name    rmse_a    rmse_b    rmse_c
        print(f"{method_name}\t{rmse_values[0]:.4f}\t{rmse_values[1]:.4f}\t{rmse_values[2]:.4f}")

if __name__ == "__main__":
    main()
