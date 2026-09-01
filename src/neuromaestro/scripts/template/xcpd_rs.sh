#!/bin/bash

# Resting-state denoising / postprocessing via XCP-D.
# --mode abcd here (adolescent cohort; interpolates censored volumes); other pipelines exist.
# --band-stop-min/-max: notch band, adjust by age. --nuisance-regressors 36P is aggressive
# (clean); XCP-D offers other denoising strategies.
# --dummy-scans: XCP-D actually drops the first REMOVE_TRS volumes (fMRIPrep only flags them);
#   set it to `auto` to auto-detect and drop the non-steady-state volumes instead.

# ---------------------------------- Setup ---------------------------------------------

subject="$1"

input_dir="$INPUT_DIR"
output_dir="$OUTPUT_DIR"
work_dir="$WORK_DIR"/xcpd/sub-${subject}

mkdir -p ${work_dir}
mkdir -p ${output_dir}

freesurfer_license="${FREESURFER_DIR}/${LICENSE}"

echo "freesurfer: ${freesurfer_license}"
echo "remove trs: ${REMOVE_TRS}"
echo "template: ${TEMPLATE}"
echo "container: ${CONTAINER_DIR}/${CONTAINER}"
echo "anaylsis mdoe: ${REST_MODE}"
echo "motion-filter-type: ${MOTION_FILTER_TYPE}"
echo "band-stop-min: ${BAND_STOP_MIN}"
echo "band-stop-max: ${BAND_STOP_MAX}"
echo "nuisance-regressors: ${NUISANCE_REGRESSORS}"

# ---------------------------------- Run Processing -------------------------------------

# notch filter parameter: https://xcp-d.readthedocs.io/en/latest/workflows.html#motion-parameter-filtering-optional 

# --nprocs below should track cpus_per_task in hpc_config.yaml.
# To follow it automatically, replace with:  --nprocs ${SLURM_CPUS_PER_TASK:-4} \
singularity run \
                -B $HOME:/home/xcp \
                --home /home/xcp \
                -B ${CONTAINER_DIR}:/resources \
                -B ${input_dir}:/data \
                -B ${work_dir}:/work \
                -B ${output_dir}:/output \
                -B ${FREESURFER_DIR}:/freesurfer \
        ${CONTAINER_DIR}/${CONTAINER} /data /output \
        participant --participant_label ${subject} \
        -w /work \
        --mode ${REST_MODE} \
        --session-id ${SESSION} \
        -t rest \
        --motion-filter-type ${MOTION_FILTER_TYPE} \
        --band-stop-min ${BAND_STOP_MIN} \
        --band-stop-max ${BAND_STOP_MAX} \
        --nuisance-regressors ${NUISANCE_REGRESSORS} \
        --create-matrices all \
        --dummy-scans ${REMOVE_TRS} \
        --nprocs 4 \
        --omp-nthreads 4 \
        --write-graph \
        --fs-license-file /freesurfer/${LICENSE}