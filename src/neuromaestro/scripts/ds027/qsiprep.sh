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

# Stage container image to node-local disk to avoid squashfuse mount timeout.
# Per-node lock: only one job copies, others wait then reuse. Fall back to the
# network image if staging fails (e.g. local disk full).
src_container="${CONTAINER_DIR}/${CONTAINER}"
node_cache="/tmp/${USER}_sif"
staged="${node_cache}/${CONTAINER}"
local_container="${src_container}"
mkdir -p "${node_cache}" 2>/dev/null
(
    flock 9
    if [ ! -s "${staged}" ] || [ "$(stat -c%s "${staged}" 2>/dev/null)" != "$(stat -c%s "${src_container}")" ]; then
        tmp_copy="${staged}.tmp.$$"
        cp "${src_container}" "${tmp_copy}" 2>/dev/null && mv -f "${tmp_copy}" "${staged}" || rm -f "${tmp_copy}"
    fi
) 9>"${node_cache}/${CONTAINER}.lock"
if [ -s "${staged}" ] && [ "$(stat -c%s "${staged}" 2>/dev/null)" = "$(stat -c%s "${src_container}")" ]; then
    local_container="${staged}"
else
    echo "WARNING: staging to ${node_cache} failed (disk full?), using network image"
fi
echo "run_container: ${local_container}"

# --nthreads below should track cpus_per_task in hpc_config.yaml.
# To follow it automatically, replace with:  --nthreads ${SLURM_CPUS_PER_TASK:-16} \
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
