import os

def extract_space_group(file_path):
    """Extract the space group (value in parentheses) from the first line of a .res file."""
    with open(file_path, 'r') as file:
        first_line = file.readline().strip()
        space_group = first_line.split('(')[-1].split(')')[0]  # Extract text between parentheses
    return space_group

def normalize_space_group(space_group):
    """
    Normalize a space group by removing slashes, underscores, hyphens, and spaces.
    """
    return space_group.replace('/', '').replace('-', '').replace('_', '').replace(' ', '').lower()

def compare_space_groups_in_filenames(directory):
    """Compare the extracted space group from file content to the space group in the filename."""
    mismatches = []

    for file_name in os.listdir(directory):
        if file_name.endswith('.res'):
            file_path = os.path.join(directory, file_name)
            try:
                # Extract the space group from the file content
                extracted_space_group = extract_space_group(file_path)

                # Extract the space group from the filename (between the first and second underscore)
                filename_space_group = file_name.split('_')[1]

                # Normalize both space groups for comparison
                normalized_extracted = normalize_space_group(extracted_space_group)
                normalized_filename = normalize_space_group(filename_space_group)

                # Compare the normalized space groups
                if normalized_extracted != normalized_filename:
                    mismatches.append((file_name, extracted_space_group, filename_space_group))
            except Exception as e:
                print(f"Error processing file {file_name}: {e}")

    # Print the results
    if mismatches:
        print("Files with mismatched space groups:")
        for file, extracted, filename_group in mismatches:
            print(f"{file}: Extracted = {extracted}, Filename = {filename_group}")
        print(f"Total mismatches: {len(mismatches)}")
    else:
        print("No mismatched space groups found.")

def main():
    directory = 'outputs/'

    # Compare the space groups in the files to those in their filenames
    compare_space_groups_in_filenames(directory)

if __name__ == "__main__":
    main()
