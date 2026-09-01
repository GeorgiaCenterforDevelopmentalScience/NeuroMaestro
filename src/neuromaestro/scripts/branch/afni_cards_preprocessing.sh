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
stimulus_dir="${STIMULUS_DIR}/cards_stim_timing_files/ses-${session}/stimulus/remove_TRs/${subj}"

t1_dir="${output_dir}/${subj}/ses-${session}/sswarp2"
nifti_dir="${input_dir}/sub-${subject}/ses-${session}/func"

echo "find: "${nifti_dir}"/sub-"${subject}"_ses-"${session}"_task-cards*.nii*"

cards_output_dir="${output_dir}/${subj}/ses-${session}/cards_output"
mkdir -p "${cards_output_dir}"

cd "${cards_output_dir}"

export AFNI_NO_X11=1

afni_proc.py \
-subj_id ${subj} \
-script proc."${subj}" -scr_overwrite \
-out_dir "${subj}.results" \
-copy_anat "${t1_dir}"/T1_results/anatSS."${subj}".nii \
-anat_has_skull no \
-dsets "${nifti_dir}"/sub-"${subject}"_ses-"${session}"_task-cards*.nii* \
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
    ${stimulus_dir}/"${subj}"_BW.1D \
    ${stimulus_dir}/"${subj}"_BL.1D \
    ${stimulus_dir}/"${subj}"_LW.1D \
    ${stimulus_dir}/"${subj}"_LL.1D \
    ${stimulus_dir}/"${subj}"_NeutralW.1D \
    ${stimulus_dir}/"${subj}"_AntLongBW.1D \
-regress_stim_labels BW BL LW LL NeutralW AntLongBW \
-regress_basis_multi 'dmBLOCK' 'dmBLOCK' 'dmBLOCK' 'dmBLOCK' 'dmBLOCK' 'dmBLOCK' \
-regress_stim_types AM1 AM1 AM1 AM1 AM1 AM1 \
-regress_opts_3dD \
-gltsym 'SYM: BW -BL' \
-gltsym 'SYM: LW -LL' \
-gltsym 'SYM: BW -NeutralW' \
-gltsym 'SYM: BL -NeutralW' \
-gltsym 'SYM: 0.5*BW +0.5*BL -NeutralW' \
-gltsym 'SYM: 0.5*LW +0.5*LL -NeutralW' \
-glt_label 1 BW-BL \
-glt_label 2 LW-LL \
-glt_label 3 BW-NeutralW \
-glt_label 4 BL-NeutralW \
-glt_label 5 BW_BL-NeutralW \
-glt_label 6 LW_LL-NeutralW \
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
