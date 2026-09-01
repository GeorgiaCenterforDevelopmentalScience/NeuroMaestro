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

singularity run \
                -B ${CONTAINER_DIR}:/resources \
                -B ${input_dir}:/data \
                -B ${work_dir}:/work \
                -B ${output_dir}:/output \
                -B ${FREESURFER_DIR}:/freesurfer \
        ${CONTAINER_DIR}/${CONTAINER} /data /output \
        participant --participant_label ${subject} \
        -w /work \
        --nthreads 16 \
        --fs-license-file /freesurfer/${LICENSE} \
        --skip_bids_validation \
        --session-label ${SESSION} \
        --dummy-scans ${REMOVE_TRS} \
        --write-graph \
        --debug all \
        --notrack \
        -t rest \
        --output-spaces ${TEMPLATE} \
        --fs-no-reconall