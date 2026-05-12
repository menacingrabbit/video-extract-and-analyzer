#!/usr/bin/env python3
"""
Merge CSV files from Video Extract and Analyzer tool.

Takes CSV file paths as arguments and merges them into a single file.
The output file uses the first file's basename with "-merged" appended.

Usage:
    python merge_csvs.py file1.csv file2.csv file3.csv
    python merge_csvs.py *.csv
"""

import os
import sys
import csv
import argparse
from pathlib import Path


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Merge CSV files from Video Extract and Analyzer tool.'
    )
    parser.add_argument(
        'csv_files',
        nargs='+',
        help='CSV files to merge (at least one required)'
    )
    parser.add_argument(
        '--output-dir', '-o',
        default=None,
        help='Directory for merged output file (default: same as first input file)'
    )
    return parser.parse_args()


def validate_csv_files(file_paths):
    """Validate that all files exist and are readable CSV files."""
    valid_files = []
    for file_path in file_paths:
        if not os.path.exists(file_path):
            print(f"Error: File not found: {file_path}")
            continue

        if not os.path.isfile(file_path):
            print(f"Error: Not a file: {file_path}")
            continue

        # Check if it's a CSV file by extension
        if not file_path.lower().endswith('.csv'):
            print(f"Warning: File doesn't have .csv extension: {file_path}")

        valid_files.append(file_path)

    return valid_files


def get_output_filename(first_file, output_dir=None):
    """Generate output filename based on first input file."""
    first_path = Path(first_file)
    base_name = first_path.stem  # filename without extension

    if output_dir:
        output_dir_path = Path(output_dir)
        output_dir_path.mkdir(parents=True, exist_ok=True)
        return output_dir_path / f"{base_name}-merged.csv"
    else:
        return first_path.parent / f"{base_name}-merged.csv"


def merge_csv_files(input_files, output_file):
    """Merge multiple CSV files into one, preserving header from first file."""
    if not input_files:
        print("Error: No valid CSV files to merge")
        return False

    if len(input_files) == 1:
        print(f"Only one file provided. Copying {input_files[0]} to {output_file}")
        try:
            import shutil
            shutil.copy2(input_files[0], output_file)
            return True
        except Exception as e:
            print(f"Error copying file: {e}")
            return False

    try:
        with open(output_file, 'w', newline='', encoding='utf-8') as outfile:
            writer = None

            for i, file_path in enumerate(input_files):
                print(f"Processing: {file_path}")

                with open(file_path, 'r', newline='', encoding='utf-8') as infile:
                    reader = csv.reader(infile)

                    # Get header from first file only
                    if i == 0:
                        header = next(reader, None)
                        if header is None:
                            print(f"Warning: {file_path} is empty")
                            continue
                        writer = csv.writer(outfile)
                        writer.writerow(header)
                    else:
                        # Skip header for subsequent files
                        next(reader, None)  # Skip header

                    # Write data rows
                    for row in reader:
                        if row:  # Skip empty rows
                            writer.writerow(row)

        print(f"Successfully merged {len(input_files)} files into: {output_file}")
        return True

    except Exception as e:
        print(f"Error merging CSV files: {e}")
        return False


def main():
    """Main function to orchestrate CSV merging."""
    args = parse_args()

    # Validate input files
    valid_files = validate_csv_files(args.csv_files)

    if not valid_files:
        print("Error: No valid CSV files provided")
        sys.exit(1)

    # Generate output filename
    output_file = get_output_filename(valid_files[0], args.output_dir)

    # Merge files
    success = merge_csv_files(valid_files, output_file)

    if success:
        print(f"Merge completed. Output: {output_file}")
    else:
        print("Merge failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()