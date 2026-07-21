#!/bin/bash

# ---------------------------------- Setup ---------------------------------------------

subject="$1"

work_dir="$WORK_DIR"/qsiprep/sub-${subject}

mkdir -p ${work_dir}
mkdir -p ${OUTPUT_DIR}

freesurfer_license="${FREESURFER_DIR}/${LICENSE}"

echo "input dir: ${INPUT_DIR}"
echo "output dir: ${OUTPUT_DIR}"
echo "work dir: ${work_dir}"
echo "freesurfer: ${freesurfer_license}"
echo "template: ${TEMPLATE}"
echo "container: ${CONTAINER_DIR}/${CONTAINER}"

# ---------------------------------- Run Processing -------------------------------------
# https://qsiprep.readthedocs.io/en/latest/quickstart.html
# NOTE: dwi/*.json in INPUT_DIR must have TotalReadoutTime, or gather_inputs crashes (no CLI override)

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
                -B ${CONTAINER_DIR}:/resources \
                -B ${INPUT_DIR}:/data \
                -B ${work_dir}:/work \
                -B ${OUTPUT_DIR}:/output \
                -B ${FREESURFER_DIR}:/freesurfer \
        ${local_container} /data /output \
        participant --participant-label ${subject} \
        -w /work \
        --nthreads 16 \
        --omp-nthreads 8 \
        --fs-license-file /freesurfer/${LICENSE} \
        --skip-bids-validation \
        --anatomical-template ${TEMPLATE} \
        --output-resolution ${OUTPUT_RESOLUTION} \
        --unringing-method ${UNRINGING_METHOD} \
        --use-syn-sdc warn \
        --force-syn \
        --notrack
