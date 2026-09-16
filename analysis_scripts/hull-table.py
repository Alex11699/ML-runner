#!/usr/bin/env python3
import os
import re
import sys  # <--- CHANGE: Import sys to read command-line arguments
import numpy as np
import matplotlib.pyplot as plt
from adjustText import adjust_text

def extract_hull_distance(file_path):
    """Extract the hull distance from a .res.txt file."""
    with open(file_path, 'r') as file:
        for line in file:
            if "Hull Distance" in line:
                match = re.search(r"Hull Distance:\s*([\d.]+)", line)
                if match:
                    return float(match.group(1))
    return None

def get_files_with_hull_distance(directory):
    """Retrieve a dictionary of file names and their extracted hull distances."""
    files_with_hull = {}
    for file_name in os.listdir(directory):
        if file_name.endswith('.res.txt'):
            file_path = os.path.join(directory, file_name)
            try:
                hull_distance = extract_hull_distance(file_path)
                if hull_distance is not None:
                    files_with_hull[file_name] = hull_distance
            except Exception as e:
                print(f"Error processing file {file_name}: {e}", file=sys.stderr)
    return files_with_hull

def rmse(a, b):
    """Calculate the Root Mean Square Error (RMSE) between two arrays."""
    return np.sqrt(np.mean((np.array(a) - np.array(b))**2))

# <--- CHANGE: Modified the function to accept a plot_mode flag and return the RMSE
def plot_rmse_hull(dft_hull, ml_hull, method_name, plot_mode=True):
    """Plot hull distance values and calculate RMSE."""
    common_files = set(dft_hull.keys()).intersection(ml_hull.keys())
    if not common_files:
        print("No matching files between directories.", file=sys.stderr)
        return None

    dft_values = [dft_hull[file] for file in common_files]
    ml_values = [ml_hull[file] for file in common_files]
    dft_array = np.array(dft_values)
    ml_array = np.array(ml_values)

    # Calculate RMSE
    rmse_value = rmse(dft_array, ml_array)

    # If not in plot mode, just return the RMSE value
    if not plot_mode:
        return rmse_value

    # --- Plotting code ---
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.scatter(dft_array, ml_array, c='blue', alpha=0.7, label='Data Points')

    max_range = max(abs(dft_array).max(), abs(ml_array).max())
    line = np.linspace(-max_range, max_range, 100)
    ax.plot(line, line, linestyle=':', color='red', label='Ideal Agreement')

    ax.set_title(f'Hull Distance Comparison: {method_name} vs DFT', fontsize=22)
    ax.set_xlabel('DFT Hull Distance (meV)', fontsize=22)
    ax.set_ylabel(f'{method_name} Hull Distance (meV)', fontsize=22)
    ax.tick_params(axis='both', which='major', labelsize=18)
    ax.text(0.95, 0.05, f'RMSE = {rmse_value:.6f} meV',
            horizontalalignment='right', verticalalignment='bottom',
            transform=ax.transAxes, fontsize=22)
    ax.grid(True)
    ax.legend()
    plt.savefig(f"RMSE_Hull_{method_name}_vs_DFT.png", format="png")
    plt.show()

    return rmse_value

# <--- CHANGE: Updated main to handle the '--table' argument
def main():
    table_mode = '--table' in sys.argv

    dft_dir = '../DFT_outputs/original-uniq-structs-Converged/'
    ml_dir = './single-points'
    method_name = os.path.basename(os.getcwd())

    dft_hull = get_files_with_hull_distance(dft_dir)
    ml_hull = get_files_with_hull_distance(ml_dir)

    rmse_value = plot_rmse_hull(dft_hull, ml_hull, method_name, plot_mode=not table_mode)

    if table_mode and rmse_value is not None:
        print(f"{method_name}\t{rmse_value:.6f}")

if __name__ == "__main__":
    main()
