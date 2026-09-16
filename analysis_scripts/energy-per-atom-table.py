#!/usr/bin/env python3
import os
import sys
import numpy as np
import matplotlib.pyplot as plt
from ase import io
from adjustText import adjust_text  # Install with: pip install adjustText


def extract_energy_per_atom(file_path):
    """Extract total energy and compute energy per atom from a .res file using ASE."""
    with open(file_path, 'r') as file:
        first_line = file.readline().strip()
        total_energy = float(first_line.split()[4])  # 5th item is at index 4

    # Use ASE to count atoms, considering periodic boundaries
    atoms = io.read(file_path, format='res')
    num_atoms = len(atoms)

    return total_energy / num_atoms if num_atoms > 0 else None

def get_files_with_energy(directory):
    """Retrieve a dictionary of file names and their extracted energy per atom."""
    files_with_energy = {}
    for file_name in os.listdir(directory):
        if file_name.endswith('.res'):
            file_path = os.path.join(directory, file_name)
            try:
                energy_per_atom = extract_energy_per_atom(file_path)
                if energy_per_atom is not None:
                    files_with_energy[file_name] = energy_per_atom
            except Exception as e:
                print(f"Error processing file {file_name}: {e}", file=sys.stderr)
    return files_with_energy

def rmse(a, b):
    """Calculate the Root Mean Square Error (RMSE) between two arrays."""
    return np.sqrt(np.mean((np.array(a) - np.array(b))**2))


def plot_rmse_energy(dft_energies, ml_energies, method_name, plot_mode=True):
    """Plot energy per atom comparison, label key points, and enable interactive selection."""
    common_files = set(dft_energies.keys()).intersection(ml_energies.keys())
    if not common_files:
        print("No matching files between directories.", file=sys.stderr)
        return None

    # Extract energy per atom values for matching files
    dft_values = {file: dft_energies[file] for file in common_files}
    ml_values = {file: ml_energies[file] for file in common_files}

    # Normalize the energy per atom values
    dft_array = np.array(list(dft_values.values()))
    ml_array = np.array(list(ml_values.values()))

    # Compute RMSE
    rmse_value = rmse(dft_array, ml_array)
    
    # If not plotting, just return the RMSE
    if not plot_mode:
        return rmse_value

    # Compute residuals (difference from ideal RMSE=0 line)
    residuals = ml_array - dft_array
    residuals_dict = {file: residuals[i] for i, file in enumerate(common_files)}

    # Find 5 largest residuals (largest absolute differences)
    largest_residuals = sorted(residuals_dict.items(), key=lambda x: abs(x[1]), reverse=True)[:5]

    # Plot
    fig, ax = plt.subplots(figsize=(8, 8))
    ax.scatter(dft_array, ml_array, c='blue', alpha=0.7, label='Data Points')

    # Plot y=x line (ideal agreement)
    max_range = max(abs(dft_array).max(), abs(ml_array).max())
    line = np.linspace(-max_range, max_range, 100)
    ax.plot(line, line, linestyle=':', color='red', label='Ideal Agreement')

    # Set axis limits to fit the data points
    plt.xlim(min(dft_array) - 1.5, max(dft_array) + 1.5)
    plt.ylim(min(ml_array) - 1.5, max(ml_array) + 1.5)

    # Annotate selected points
    texts = []
    for file, residual in largest_residuals:
        texts.append(ax.text(dft_values[file], ml_values[file], file, fontsize=8, color='purple', alpha=0.7))

    # Adjust text to avoid overlap
    adjust_text(texts, arrowprops=dict(arrowstyle="->", color='gray', lw=0.5))

    def on_click(event):
        if event.xdata is None or event.ydata is None:
            return  # Ignore clicks outside the plot

        # Debugging print to see what coordinates are captured
        print(f"Clicked at: x = {event.xdata}, y = {event.ydata}")

        # Calculate distances from click to data points
        distances = [(x - event.xdata)**2 + (y - event.ydata)**2 for x, y in zip(dft_array, ml_array)]

        # Get the index of the closest point
        closest_index = distances.index(min(distances))
        closest_file = list(common_files)[closest_index]
        
        print(f"Closest file: {closest_file}")

    # Connect the click event to the figure
    fig.canvas.mpl_connect('button_press_event', on_click)

    # Add labels and title
    ax.set_title(f'Energy per Atom Comparison: {method_name} vs DFT', fontsize=20)
    ax.set_xlabel('DFT Energy per Atom (eV)', fontsize=20)
    ax.set_ylabel(f'{method_name} Energy per Atom (eV)', fontsize=20)
    ax.text(0.95, 0.05, f'RMSE = {rmse_value:.6f} eV',
            horizontalalignment='right', verticalalignment='bottom',
            transform=ax.transAxes, fontsize=20)

    ax.legend()
    ax.grid(True)
    plt.savefig(f"RMSE_{method_name}_vs_DFT.png", format="png")
    plt.show()
    
    return rmse_value


def main():
    # Check if running in table mode (no plots)
    table_mode = '--table' in sys.argv or '--rmse-only' in sys.argv
    
    dft_dir = '../DFT_outputs/original-uniq-structs-Converged'  # Adjust this path as needed
    ml_dir = './single-points'  # Adjust this path as needed
    method_name = os.path.basename(os.getcwd())  # Get ML method name from the current working directory

    # Retrieve energy per atom values for both directories
    dft_energies = get_files_with_energy(dft_dir)
    ml_energies = get_files_with_energy(ml_dir)

    # Plot and compare (or just get RMSE in table mode)
    rmse_value = plot_rmse_energy(dft_energies, ml_energies, method_name, plot_mode=not table_mode)
    
    if table_mode and rmse_value is not None:
        # Output in a format easy to parse: method_name RMSE
        print(f"{method_name}\t{rmse_value:.6f}")

if __name__ == "__main__":
    main()
