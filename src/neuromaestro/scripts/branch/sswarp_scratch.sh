#!/bin/bash

# ---------------------------------- Setup ---------------------------------------------

subject="$1"

# Use the global variables
input_dir="$INPUT_DIR"
output_dir="$OUTPUT_DIR"
work_dir="$WORK_DIR"
prefix="$PREFIX"
session="$SESSION"

mkdir -p "$output_dir"
mkdir -p "$work_dir"

template="$TEMPLATE_DIR/$TEMPLATE"

echo "Template: $TEMPLATE"
echo "Input directory: $INPUT_DIR"
echo "Output directory: $OUTPUT_DIR"
echo "template: ${template}"
# ---------------------------------- Run Processing -------------------------------------
# 
subj="${prefix}${subject}"
t1_dir="${output_dir}/${subj}/ses-${session}/sswarp2"
nifti_dir="${input_dir}/sub-${subject}/ses-${session}/anat"

export AFNI_NO_X11=1

# Create T1_results folder
mkdir -p "$t1_dir/T1_results"

nifti_files=(${nifti_dir}/sub-${subject}_ses-${session}_*T1w*.nii*)

if [ ${#nifti_files[@]} -gt 1 ]; then
    echo "Error: Found more than one T1w NIfTI file for subject $subject:"
    for f in "${nifti_files[@]}"; do
        echo "  $f"
    done
    exit 1
elif [ ${#nifti_files[@]} -eq 0 ]; then
    echo "Error: No T1w NIfTI file found for subject $subject"
    exit 1
fi

nifti_file=${nifti_files[0]}
echo "processing: $nifti_file"
echo "ID: $subj"

sswarper2 \
    -input "$nifti_file" \
    -base "$template" \
    -subid "$subj" \
    -deoblique_refitly \
    -giant_move \
    -odir "$t1_dir/T1_results" 2>&1 | tee "$t1_dir/log_$subj.txt"

echo "finished processing"