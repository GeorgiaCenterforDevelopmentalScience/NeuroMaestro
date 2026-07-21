#!/bin/bash

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

# Point Apptainer session/cache to node-local disk to avoid squashfuse mount timeout
apptainer_tmp="${SLURM_TMPDIR:-${TMPDIR:-/tmp}}/apptainer_${SLURM_JOB_ID:-$$}"
mkdir -p "${apptainer_tmp}"
export APPTAINER_TMPDIR="${apptainer_tmp}"
export APPTAINER_CACHEDIR="${apptainer_tmp}"
export SINGULARITY_TMPDIR="${apptainer_tmp}"
export SINGULARITY_CACHEDIR="${apptainer_tmp}"

# Stage container image to node-local disk (copied once per node, then reused)
node_cache="/tmp/${USER}_sif"
mkdir -p "${node_cache}"
src_container="${CONTAINER_DIR}/${CONTAINER}"
local_container="${node_cache}/${CONTAINER}"
if [ ! -s "${local_container}" ] || \
   [ "$(stat -c%s "${local_container}" 2>/dev/null)" != "$(stat -c%s "${src_container}")" ]; then
    tmp_copy="${local_container}.tmp.$$"
    cp "${src_container}" "${tmp_copy}" && mv -f "${tmp_copy}" "${local_container}"
fi

singularity run \
                -B $HOME:/home/xcp \
                --home /home/xcp \
                -B ${CONTAINER_DIR}:/resources \
                -B ${input_dir}:/data \
                -B ${work_dir}:/work \
                -B ${output_dir}:/output \
                -B ${FREESURFER_DIR}:/freesurfer \
        ${local_container} /data /output \
        participant --participant_label ${subject} \
        -w /work \
        --mode ${REST_MODE} \
        -t restingstate \
        --motion-filter-type ${MOTION_FILTER_TYPE} \
        --band-stop-min ${BAND_STOP_MIN} \
        --band-stop-max ${BAND_STOP_MAX} \
        --nuisance-regressors ${NUISANCE_REGRESSORS} \
        --dummy-scans ${REMOVE_TRS} \
        --nprocs 4 \
        --omp-nthreads 4 \
        --write-graph \
        --fs-license-file /freesurfer/${LICENSE}