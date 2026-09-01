#!/bin/bash

# Single-subject ICA task preprocessing via afni_proc.py.

# Note:
# In general, scale is not recommended for ICA; `despike` is used here instead of the
# traditional scaling step. AFNI writes a dataset per step: for blur-only output take the
# last pb* file and convert to NIfTI; for high-pass + motion-regressed output take the
# errts* file.

# ---------------------------------- Setup ---------------------------------------------

subject="$1"
echo "Processing subject: $subject for ICA task preprocessing"

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
echo "bandpass: ${BANDPASS_LOW} - ${BANDPASS_HIGH}"

# ---------------------------------- Run Processing -------------------------------------

subj="${prefix}${subject}"
t1_dir="${output_dir}/${subj}/ses-${session}/sswarp2"
nifti_dir="${input_dir}/sub-${subject}/ses-${session}/func"

ica_task_output_dir="${output_dir}/${subj}/ses-${session}/ica_task_output"
mkdir -p "${ica_task_output_dir}"

cd "${ica_task_output_dir}"

echo "find "${nifti_dir}"/sub-"${subject}"_ses-"${session}"_task-kidvid*.nii*"

if ! ls "${nifti_dir}"/sub-"${subject}"_ses-"${session}"_task-kidvid*.nii* 1> /dev/null 2>&1; then
    echo "Not found nii file or maybe the name is wrong in ${nifti_dir}"
    exit 1
fi

export AFNI_NO_X11=1

afni_proc.py \
-subj_id $subj \
-script proc."${subj}" -scr_overwrite \
-out_dir "${subj}.results" \
-copy_anat "${t1_dir}"/T1_results/anatSS."${subj}".nii \
-anat_has_skull no \
-dsets "${nifti_dir}"/sub-"${subject}"_ses-"${session}"_task-kidvid*.nii* \
-blocks despike tshift align tlrc volreg blur mask regress \
-radial_correlate_blocks tcat volreg regress \
-tcat_remove_first_trs "${REMOVE_TRS}" \
-align_unifize_epi local \
-align_opts_aea -cost lpc+ZZ -giant_move -check_flip \
-tlrc_base "${template}" \
-tlrc_NL_warp \
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
-regress_apply_mot_types demean deriv \
-regress_motion_per_run \
-regress_censor_motion "${CENSOR_MOTION}" \
-regress_censor_outliers "${CENSOR_OUTLIERS}" \
-regress_bandpass "${BANDPASS_LOW}" "${BANDPASS_HIGH}" \
-regress_est_blur_epits \
-regress_est_blur_errts \
-regress_run_clustsim no \
-html_review_style pythonic \
-execute \
