#!/bin/bash

# ICA task postprocess: per-subject FSL MELODIC on the afni_proc.py output.
# Converts the +tlrc BOLD and its full_mask to NIfTI, runs individual MELODIC, and also
# leaves an uncompressed .nii for group-level ICA (GIFT/MATLAB, run separately).

# ---------------------------------- Setup ---------------------------------------------

subject="$1"
echo "Processing subject: $subject for ICA task postprocessing"

output_dir="$OUTPUT_DIR"
prefix="$PREFIX"
session="$SESSION"

subj="${prefix}${subject}"

in_dir="${output_dir}/${subj}/ses-${session}/ica_task_output/${subj}.results"
in_dset="${in_dir}/${AFNI_DSET}.${subj}+tlrc"
in_mask="${in_dir}/full_mask.${subj}+tlrc"

out_dir="${output_dir}/${subj}/ses-${session}/ica_task_output"
bold_gz="${out_dir}/${subj}_preproc.nii.gz"
bold_nii="${out_dir}/${subj}_preproc.nii"
mask_gz="${out_dir}/${subj}_mask.nii.gz"
melodic_dir="${out_dir}/${subj}.melodic"

echo "Input dataset: ${in_dset}"
echo "MELODIC output: ${melodic_dir}"
echo "mmthresh: ${MMTHRESH}"

# ---------------------------------- Run Processing -------------------------------------

# convert AFNI +tlrc -> .nii.gz (BOLD + full_mask; same grid, no resample needed)
if [[ ! -f "${in_dset}.HEAD" || ! -f "${in_dset}.BRIK.gz" ]]; then
    echo "[MISSING] ${in_dset}.HEAD/.BRIK.gz — exiting."
    exit 1
fi

echo "[$(date +%T)] Converting ${subj} ..."
3dAFNItoNIFTI -prefix "${bold_gz}" "${in_dset}"
[[ -f "${in_mask}.HEAD" ]] && 3dAFNItoNIFTI -prefix "${mask_gz}" "${in_mask}"

if [[ ! -f "${bold_gz}" ]]; then
    echo "[ERROR] 3dAFNItoNIFTI failed"
    exit 1
fi

# individual ICA (default analysis): MELODIC on this subject, masked by full_mask.
# run before the decompress below, which deletes the .nii.gz MELODIC reads.
mask_opt=""
[[ -f "${mask_gz}" ]] && mask_opt="-m ${mask_gz}"
echo "[$(date +%T)] Running MELODIC for ${subj} ..."
melodic \
    -i "${bold_gz}" \
    $mask_opt \
    -o "${melodic_dir}" \
    --Oall \
    -a concat \
    --report \
    --verbose \
    --nobet \
    --mmthresh="${MMTHRESH}"

# decompress .nii.gz -> .nii for group-level ICA (GIFT/MATLAB, run separately)
echo "[$(date +%T)] Decompressing ${subj} ..."
env -u PYTHONPATH fslchfiletype NIFTI "${bold_gz}"

echo "[OK] ${subj} -> ${melodic_dir}"

# ---------------------------------- Group ICA (manual) --------------------------------
# Group-level ICA is a separate MATLAB step, not run by this pipeline. Collect the
# per-subject ${subj}_preproc.nii paths into a list file (one per line), then run GIFT's
# gica_cmd. Set the placeholder paths per project.
#
#   ml matlab
#   # add SPM + GIFT to the MATLAB path (interactively or via startup.m):
#   #   addpath(genpath('/path/to/spm'))
#   #   addpath(genpath('/path/to/gift'))

#   gica_cmd --data /path/to/group/all.txt --modality fmri \
#            --algorithm infomax --preproc 3 --recon gica --icasso 5 --prefix test \
#            --dummy 0 --gtype spatial --o /path/to/group/output \
#            --mask default --parallel 4 --performance 1 --sess 1 --display 1
