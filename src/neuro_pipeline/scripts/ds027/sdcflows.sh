#!/bin/bash

# ---------------------------------- Setup ---------------------------------------------

subject="$1"

echo "Processing subject: $subject for SDCFlows fieldmap estimation"

input_dir="$INPUT_DIR"
output_dir="$OUTPUT_DIR"
work_dir="$WORK_DIR"/sdc_work/sub-${subject}

mkdir -p ${work_dir}
mkdir -p ${output_dir}

# ---------------------------------- Run Processing -------------------------------------

singularity run \
    -B ${input_dir}:/data \
    -B ${work_dir}:/work \
    -B ${output_dir}:/output \
    ${CONTAINER_DIR}/${CONTAINER} \
    sdcflows /data /output \
    participant --participant-label ${subject} \
    -w /work \
    --notrack \
    -v --debug
