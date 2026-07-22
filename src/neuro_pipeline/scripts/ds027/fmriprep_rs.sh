#!/bin/bash

# ---------------------------------- Setup ---------------------------------------------


subject="$1"

input_dir="$INPUT_DIR"
output_dir="$OUTPUT_DIR"
work_dir="$WORK_DIR"/fmriprep/sub-${subject}
freesurfer_license="${FREESURFER_DIR}/${LICENSE}"

mkdir -p ${work_dir}
mkdir -p ${output_dir}

echo "freesurfer: ${freesurfer_license}"
echo "remove trs: ${REMOVE_TRS}"
echo "template: ${TEMPLATE}"
echo "container: ${CONTAINER_DIR}/${CONTAINER}"

# ---------------------------------- Run Processing -------------------------------------

# If you want to use HaskinsPeds template you need to make and upload it to the template folder.
# See https://fmriprep.org/en/stable/spaces.html

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

singularity run \
                -B ${CONTAINER_DIR}:/resources \
                -B ${input_dir}:/data \
                -B ${work_dir}:/work \
                -B ${output_dir}:/output \
                -B ${FREESURFER_DIR}:/freesurfer \
        ${local_container} /data /output \
        participant --participant_label ${subject} \
        -w /work \
        --nthreads 16 \
        --fs-license-file /freesurfer/${LICENSE} \
        --skip_bids_validation \
        --dummy-scans ${REMOVE_TRS} \
        --use-syn-sdc warn \
        --force syn-sdc \
        --write-graph \
        --debug all \
        --notrack \
        -t restingstate \
        --cifti-output 91k \
        --output-spaces T1w ${TEMPLATE}