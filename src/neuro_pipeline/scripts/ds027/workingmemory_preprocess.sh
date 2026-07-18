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
echo "remove trs: ${REMOVE_TRS}"

echo "smoothing or blur size: ${BLUR_SIZE}"
echo "censor_motion: ${CENSOR_MOTION}"
echo "censor_outliers: ${CENSOR_OUTLIERS}"

# ---------------------------------- Run Processing -------------------------------------
subj="${prefix}${subject}"

echo "stimulus directory: ${STIMULUS_DIR}"
stimulus_dir="${STIMULUS_DIR}/${subj}"

t1_dir="${output_dir}/${subj}/ses-${session}/sswarp2"
nifti_dir="${input_dir}/sub-${subject}/func"

echo "find: "${nifti_dir}"/sub-"${subject}"_task-workingmemory_acq-seq_bold.nii.gz"

workingmemory_output_dir="${output_dir}/${subj}/ses-${session}/workingmemory_output"
mkdir -p "${workingmemory_output_dir}"

cd "${workingmemory_output_dir}"

export AFNI_NO_X11=1

afni_proc.py \
-subj_id ${subj} \
-script proc."${subj}" -scr_overwrite \
-out_dir "${subj}.results" \
-copy_anat "${t1_dir}"/T1_results/anatSS."${subj}".nii \
-anat_has_skull no \
-dsets "${nifti_dir}"/sub-"${subject}"_task-workingmemory_acq-seq_bold.nii.gz \
-blocks tshift align tlrc volreg blur mask scale regress \
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
-test_stim_files no \
-blur_size "${BLUR_SIZE}" \
-regress_stim_times \
    ${stimulus_dir}/"${subj}"_workingmemory_active_change.1D \
    ${stimulus_dir}/"${subj}"_workingmemory_active_nochange.1D \
    ${stimulus_dir}/"${subj}"_workingmemory_passive.1D \
-regress_stim_labels change nochange passive \
-regress_basis_multi 'dmBLOCK' 'dmBLOCK' 'dmBLOCK' \
-regress_stim_types AM1 AM1 AM1 \
-regress_opts_3dD \
-gltsym 'SYM: change -nochange' \
-gltsym 'SYM: change -passive' \
-gltsym 'SYM: nochange -passive' \
-gltsym 'SYM: 0.5*pos +0.5*neg -neut' \
-glt_label 1 change-nochange \
-glt_label 2 change-passive \
-glt_label 3 nochange-nochange \
-glt_label 4 PosNeg-Neut \

-regress_censor_motion "${CENSOR_MOTION}" \
-regress_censor_outliers "${CENSOR_OUTLIERS}" \
-regress_motion_per_run \
-regress_3dD_stop \
-regress_reml_exec \
-regress_compute_fitts \
-regress_make_ideal_sum sum_ideal.1D \
-regress_est_blur_epits \
-regress_est_blur_errts \
-regress_run_clustsim no \
-html_review_style pythonic \
-execute \
