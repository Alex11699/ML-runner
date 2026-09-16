#!/usr/bin/env python3
import os
import re
import sys  # <--- CHANGE: Import sys to read command-line arguments
import numpy as np
import matplotlib.pyplot as plt

def extract_cell_volume(file_path):
    """Extract the cell volume from a .res.txt file."""
    with open(file_path, 'r') as file:
        for line in file:
            if "Cell volume" in line:
                match = re.search(r"Cell volume:\s*([\d.]+)", line)
                if match:
                    return float(match.group(1))
    return None

def get_files_with_volume(directory):
    """Retrieve a dictionary of file names and their extracted cell volumes."""
    files_with_volume = {}
    for file_name in os.listdir(directory):
        if file_name.endswith('.res.txt'):
            file_path = os.path.join(directory, file_name)
            try:
                volume = extract_cell_volume(file_path)
                if volume is not None:
                    files_with_volume[file_name] = volume
            except Exception as e:
                print(f"Error processing file {file_name}: {e}", file=sys.stderr)
    return files_with_volume

def rmse(a, b):
    """Calculate the Root Mean Square Error (RMSE) between two arrays."""
    return np.sqrt(np.mean((np.array(a) - np.array(b))**2))

# <--- CHANGE: Modified the function to accept a plot_mode flag and return the RMSE
def plot_rmse_volume(dft_volumes, ml_volumes, method_name, plot_mode=True):
    """Plot normalized cell volume values and calculate RMSE."""
    common_files = set(dft_volumes.keys()).intersection(ml_volumes.keys())
    if not common_files:
        print("No matching files between directories.", file=sys.stderr)
        return None

    # Extract volume values for matching files
    dft_values = [dft_volumes[file] for file in common_files]
    ml_values = [ml_volumes[file] for file in common_files]

    # Normalize the volume values by subtracting their mean
    dft_normalized = np.array(dft_values) - np.mean(dft_values)
    ml_normalized = np.array(ml_values) - np.mean(ml_values)

    # Calculate RMSE
    rmse_value = rmse(dft_normalized, ml_normalized)

    # If not in plot mode, just return the RMSE value
    if not plot_mode:
        return rmse_value

    # --- Plotting code remains the same ---
    plt.figure(figsize=(8, 8))
    plt.scatter(dft_normalized, ml_normalized, c='blue', alpha=0.7, label='Data Points')

    # Plot y=x line (ideal agreement)
    max_range = max(abs(dft_normalized).max(), abs(ml_normalized).max())
    line = np.linspace(-max_range, max_range, 100)
    plt.plot(line, line, linestyle=':', color='red', label='Ideal Agreement')

    # Add labels and titles
    plt.title(f'Cell Volume Comparison: {method_name} vs DFT', fontsize=22)
    plt.xlabel('DFT Normalized Cell Volume (Å³)', fontsize=22)
    plt.ylabel(f'{method_name} Normalized Cell Volume (Å³)', fontsize=22)
    plt.tick_params(axis='both', which='major', labelsize=18)
    plt.text(0.95, 0.05, f'RMSE = {rmse_value:.6f} Å³',
             horizontalalignment='right', verticalalignment='bottom',
             transform=plt.gca().transAxes, fontsize=22)

    plt.grid(True)
    plt.legend()
    plt.savefig(f"RMSE_Volume_{method_name}_vs_DFT.png", format="png")
    plt.show()
    
    return rmse_value

# <--- CHANGE: Updated main to handle the '--table' argument
def main():
    # Check if running in table mode (no plots)
    table_mode = '--table' in sys.argv

    dft_dir = '../DFT_outputs/original-uniq-structs-Converged/'
    ml_dir = './single-points'
    method_name = os.path.basename(os.getcwd())

    # Retrieve cell volume values
    dft_volumes = get_files_with_volume(dft_dir)
    ml_volumes = get_files_with_volume(ml_dir)

    # Plot and compare (or just get RMSE in table mode)
    # Pass 'plot_mode=not table_mode' to the function
    rmse_value = plot_rmse_volume(dft_volumes, ml_volumes, method_name, plot_mode=not table_mode)

    # If in table mode, print the result in the required format
    if table_mode and rmse_value is not None:
        # Output: method_name    RMSE_value
        print(f"{method_name}\t{rmse_value:.6f}")

if __name__ == "__main__":
    main()
