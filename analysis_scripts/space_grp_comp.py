import os

def extract_space_group(file_path):
    """Extract the space group (value in parentheses) from the first line of a .res file."""
    with open(file_path, 'r') as file:
        first_line = file.readline().strip()
        space_group = first_line.split('(')[-1].split(')')[0]  # Extract text between parentheses
    return space_group

def get_files_with_space_groups(directory):
    """Retrieve a dictionary of file names and their extracted space groups."""
    files_with_space_groups = {}
    for file_name in os.listdir(directory):
        if file_name.endswith('.res'):
            file_path = os.path.join(directory, file_name)
            try:
                space_group = extract_space_group(file_path)
                files_with_space_groups[file_name] = space_group
            except Exception as e:
                print(f"Error processing file {file_name}: {e}")
    return files_with_space_groups

def compare_space_groups(dft_space_groups, ml_space_groups):
    """Compare space groups between two dictionaries and print mismatches."""
    common_files = set(dft_space_groups.keys()).intersection(ml_space_groups.keys())
    mismatches = []

    for file in common_files:
        if dft_space_groups[file] != ml_space_groups[file]:
            mismatches.append((file, dft_space_groups[file], ml_space_groups[file]))

    if mismatches:
        print("Files with mismatched space groups:")
        for file, dft_group, ml_group in mismatches:
            print(f"{file}: DFT = {dft_group}, ML = {ml_group}")
        print(f"Total mismatches: {len(mismatches)}")
    else:
        print("No mismatched space groups found.")

def main():
    dft_dir = 'DFT_outputs'
    ml_dir = 'outputs'

    # Retrieve space group values for both directories
    dft_space_groups = get_files_with_space_groups(dft_dir)
    ml_space_groups = get_files_with_space_groups(ml_dir)

    # Compare and list mismatched space groups
    compare_space_groups(dft_space_groups, ml_space_groups)

if __name__ == "__main__":
    main()
