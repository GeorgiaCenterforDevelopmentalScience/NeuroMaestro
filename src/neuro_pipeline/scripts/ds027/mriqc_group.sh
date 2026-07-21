#!/bin/bash
 
# ---------------------------------- Setup ---------------------------------------------

subject="$1"

input_dir="$INPUT_DIR"
output_dir="$OUTPUT_DIR"
work_dir="$WORK_DIR"/mriqc/

mkdir -p ${work_dir}
mkdir -p ${output_dir}

echo "$INPUT_DIR"
echo "$OUTPUT_DIR"

# ---------------------------------- Run Processing -------------------------------------

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
                -B ${input_dir}:/data \
                -B ${work_dir}:/work \
                -B ${output_dir}:/output \
        ${local_container} /data /output \
        group \
        -w /work \
        --no-sub \
        --nprocs 16 \
        --notrack \
        --omp-nthreads 4 \
        --verbose-reports \
        --write-graph \
        -vv

# BUG FIX: Delete old PyBIDS cache before running.
# This prevents MRIQC from crashing with "empty result" (corrupted cache) 
# or "Directory not empty" (HPC overwrite conflict).
# rm -rf ${output_dir}/.bids_db
# --bids-database-wipe \