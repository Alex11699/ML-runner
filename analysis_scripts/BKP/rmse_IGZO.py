import os
import numpy as np
import matplotlib.pyplot as plt

def extract_energy(file_path):
    """Extract the 5th item (energy value) from the first line of a .res file."""
    with open(file_path, 'r') as file:
        first_line = file.readline().strip()
        energy = float(first_line.split()[4])  # 5th item is at index 4
    return energy

def get_files_with_energy(directory):
    """Retrieve a dictionary of file names and their extracted energies."""
    files_with_energy = {}
    for file_name in os.listdir(directory):
        if file_name.endswith('.res'):
            file_path = os.path.join(directory, file_name)
            try:
                energy = extract_energy(file_path)
                files_with_energy[file_name] = energy
            except Exception as e:
                print(f"Error processing file {file_name}: {e}")
    return files_with_energy

def rmse(a, b):
    """Calculate the Root Mean Square Error (RMSE) between two arrays."""
    return np.sqrt(np.mean((np.array(a) - np.array(b))**2))

def plot_rmse_energy(dft_energies, ml_energies, method_name):
    """Plot normalized energy values and calculate RMSE."""
    common_files = set(dft_energies.keys()).intersection(ml_energies.keys())
    if not common_files:
        print("No matching files between directories.")
        return

    # Extract energy values for matching files
    dft_values = [dft_energies[file] for file in common_files]
    ml_values = [ml_energies[file] for file in common_files]

    # Normalize the energy values by subtracting their mean
    dft_normalized = np.array(dft_values) - np.mean(dft_values)
    ml_normalized = np.array(ml_values) - np.mean(ml_values)

    # Calculate RMSE
    rmse_value = rmse(dft_normalized, ml_normalized)

    # Plot the data
    plt.figure(figsize=(8, 8))
    plt.scatter(dft_normalized, ml_normalized, c='blue', alpha=0.7, label='Data Points')

    # Plot y=x line (ideal agreement)
    max_range = max(abs(dft_normalized).max(), abs(ml_normalized).max())
    line = np.linspace(-max_range, max_range, 100)
    plt.plot(line, line, linestyle=':', color='red', label='Ideal Agreement')

    # Add labels and titles
    plt.title(f'Energy Comparison: {method_name} vs DFT', fontsize=16)
    plt.xlabel('DFT Normalized Energy (eV)', fontsize=14)
    plt.ylabel(f'{method_name} Normalized Energy (eV)', fontsize=14)
    plt.text(0.95, 0.05, f'RMSE = {rmse_value:.6f} eV',
             horizontalalignment='right', verticalalignment='bottom',
             transform=plt.gca().transAxes, fontsize=12)

    plt.legend()
    plt.grid(True)
    plt.savefig(f"RMSE_{method_name}_vs_DFT.pdf", format="pdf")
    plt.show()

def main():
    dft_dir = 'DFT_outputs'
    ml_dir = 'outputs'
    method_name = os.path.basename(os.getcwd())  # Get ML method name from the current working directory

    # Retrieve energy values for both directories
    dft_energies = get_files_with_energy(dft_dir)
    ml_energies = get_files_with_energy(ml_dir)

    # Plot and compare
    plot_rmse_energy(dft_energies, ml_energies, method_name)

if __name__ == "__main__":
    main()
