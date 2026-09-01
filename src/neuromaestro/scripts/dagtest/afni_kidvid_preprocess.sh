#!/bin/bash

# ---------------------------------- Setup ---------------------------------------------

# echo "PATH: $PATH"
# echo "PYTHONPATH: $PYTHONPATH"
# echo "LD_LIBRARY_PATH: $LD_LIBRARY_PATH"

subject="$1"
echo "Processing subject: $subject for BIDS reconstruction"

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
echo "remove trs: ${REMOVE_TRS}"
echo "smoothing or blur size: ${BLUR_SIZE}"
echo "censor_motion: ${CENSOR_MOTION}"
echo "censor_outliers: ${CENSOR_OUTLIERS}"

# ---------------------------------- Run Processing -------------------------------------
echo "stimulus directory: ${STIMULUS_DIR}"
stimulus_dir="${STIMULUS_DIR}/kidvid_stim_timing_files"

subj="${prefix}${subject}"
t1_dir="${output_dir}/${subj}/ses-${session}/sswarp2"
nifti_dir="${input_dir}/sub-${subject}/ses-${session}/func"

kidvid_output_dir="${output_dir}/${subj}/ses-${session}/kidvid_output"
mkdir -p "${kidvid_output_dir}"

cd "${kidvid_output_dir}"

# env > env.sbatch.log

echo "find "${nifti_dir}"/sub-"${subject}"_ses-"${session}"_task-kidvid*.nii*"

if ! ls "${nifti_dir}"/sub-"${subject}"_ses-"${session}"_task-kidvid*.nii* 1> /dev/null 2>&1; then
    echo "Not found nii file or maybe the name is wrong in $data_dir"
    exit 1
fi

if ls "${nifti_dir}"/sub-"${subject}"_ses-"${session}"_task-kidvidB*.nii* 1> /dev/null 2>&1; then
    version="B"
else
    version="A"
fi

echo "version: ${version}"

export AFNI_NO_X11=1

# https://afni.nimh.nih.gov/pub/dist/doc/htmldoc/programs/alpha/afni_proc.py_sphx.html#example-2-very-simple

afni_proc.py \
-subj_id $subj \
-script proc."${subj}" -scr_overwrite \
-out_dir "${subj}.results" \
-copy_anat "${t1_dir}"/T1_results/anatSS."${subj}".nii \
-anat_has_skull no \
-dsets "${nifti_dir}"/sub-"${subject}"_ses-"${session}"_task-kidvid*.nii* \
-blocks tshift align tlrc volreg mask blur scale regress \
-radial_correlate_blocks  tcat volreg regress \
-tcat_remove_first_trs "${REMOVE_TRS}" \
-align_unifize_epi local \
-align_opts_aea -cost lpc+ZZ -giant_move \
-tlrc_base "${template}" \
-tlrc_NL_warped_dsets \
    "${t1_dir}"/T1_results/anatQQ."${subj}".nii \
    "${t1_dir}"/T1_results/anatQQ."${subj}".aff12.1D \
    "${t1_dir}"/T1_results/anatQQ."${subj}"_WARP.nii \
-volreg_align_to MIN_OUTLIER \
-volreg_align_e2a \
-volreg_tlrc_warp \
-volreg_compute_tsnr yes \
-mask_epi_anat yes \
-blur_size "${BLUR_SIZE}" \
-regress_stim_times \
	"${stimulus_dir}"/${version}_remove_6TRs/negative.1D \
	"${stimulus_dir}"/${version}_remove_6TRs/neutral.1D \
-regress_stim_labels neg neut \
-regress_basis_multi 'dmBLOCK' 'dmBLOCK' \
-regress_stim_types AM1 AM1 \
-regress_censor_motion "${CENSOR_MOTION}" \
-regress_censor_outliers "${CENSOR_OUTLIERS}" \
-regress_motion_per_run \
-regress_3dD_stop \
-regress_reml_exec \
-regress_compute_fitts \
-regress_make_ideal_sum sum_ideal.1D \
-regress_run_clustsim no \
-html_review_style pythonic