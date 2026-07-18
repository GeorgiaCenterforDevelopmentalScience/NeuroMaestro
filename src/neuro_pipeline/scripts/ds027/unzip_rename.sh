#!/bin/bash

echo "=== unzip_rename.sh ==="
echo "current path: $(pwd)"
echo "SCRIPT_DIR: $SCRIPT_DIR"
echo "INPUT_DIR: $INPUT_DIR"
echo "OUTPUT_DIR: $OUTPUT_DIR"
echo "WORK_DIR: $WORK_DIR"
echo "subject: $1"
echo "session: $SESSION"

# ---------------------------------- Setup ---------------------------------------------

subject="$1"
echo "Unzip all files: $subject"

prefix="$PREFIX"

# Use the global variables
input_dir="$INPUT_DIR"
output_dir="$OUTPUT_DIR"/ses-${SESSION}
work_dir="$WORK_DIR"


mkdir -p "$work_dir"
mkdir -p "$output_dir"
# ---------------------------------- Run Scripts ---------------------------------------------

cd "$input_dir" || { echo "Error: Cannot access $input_dir"; exit 1; }

find "$input_dir" -name "*.zip" -print0 | parallel --jobs 5 -0 "7z x {} -o\"$output_dir\" -aos 2>> \"$output_dir/unzip_errors.log\""

# ==================
# Rename Folders
# ==================

cd "$output_dir" || { echo "Error: Cannot access $output_dir"; exit 1; }

# Create CSV file
csv_file=$output_dir/"dicom_summary_$(date '+%Y-%m-%d_%H-%M-%S').csv"

# Write CSV header
echo "e_Folder Name,ID,custom_id,File,File Path" > "$csv_file"

# Iterate through e-prefixed directories
for e_dir in e*/; do
    # Remove trailing /
    e_dir=${e_dir%/}
    
    # Find first file with MRDC or first file in s-prefixed subdirectories
    file=""
    for s_dir in "$e_dir"/s*/; do
        # Prefer MRDC files, otherwise take first file
        file=$(find "$s_dir" -type f | grep -m 1 "MRDC")
        
        # If no MRDC file, take first file
        if [ -z "$file" ]; then
            file=$(find "$s_dir" -type f -print -quit)
        fi
        
        # Exit loop if file found
        if [ -n "$file" ]; then
            break
        fi
    done
    
    # Process found file
    if [ -n "$file" ]; then
        # Extract Patient ID
        patient_id=$(dicom_hdr "$file" | grep "Patient ID" | awk -F'//' '{print $3}' | tr -d ' ')
        
        # Extract branch number (remove leading letters and take first number group)
        number=$(echo "$patient_id" | sed -E 's/^[^0-9]*([0-9]+).*/\1/')
        custom_id="${prefix}${number}"

        # Record in CSV
        echo "$e_dir,$patient_id,$custom_id,$(basename "$file"),$file" >> "$csv_file"
    fi
done

# Display console output
echo "DICOM Summary:"
echo "Folder Name | Patient ID | Custom ID | First File"
echo "-------------------------------"
cat "$csv_file" | tail -n +2 | column -t -s,

echo -e "\nOutput file created: $csv_file"

# Create a log file for renaming operations
rename_log=$output_dir/"rename_log_$(date '+%Y-%m-%d_%H-%M-%S').txt"
echo "Renaming Log - $(date)" > "$rename_log"

# Skip the header and process each line
tail -n +2 "$csv_file" | while IFS=',' read -r folder_name patient_id custom_id first_file file_path
do
    # Check if custom_id is valid and different from folder_name
    if [ -n "$custom_id" ] && [ "$custom_id" != "$folder_name" ]; then
        # Ensure the old directory exists
        if [ -d "$folder_name" ]; then
            # Attempt to rename
            if mv "$folder_name" "$custom_id"; then
                echo "Renamed: $folder_name -> $custom_id" >> "$rename_log"
            else
                echo "Error renaming $folder_name to $custom_id" >> "$rename_log"
            fi
        else
            echo "Directory $folder_name does not exist" >> "$rename_log"
        fi
    else
        echo "Skipping: $folder_name (invalid or same name)" >> "$rename_log"
    fi
done

# Display log contents
cat "$rename_log"
