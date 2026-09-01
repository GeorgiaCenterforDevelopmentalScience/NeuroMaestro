#!/bin/bash

# ---------------------------------- Setup ---------------------------------------------

subject="$1"

echo "Processing subject: $subject for BIDS reconstruction"
echo "${SESSION}"


input_dir="$INPUT_DIR"
output_dir="$OUTPUT_DIR"
work_dir="$WORK_DIR"/mriqc/sub-${subject}

mkdir -p ${work_dir}
mkdir -p ${output_dir}

# --deoblique \
# ml afni module

# ---------------------------------- Run Processing -------------------------------------

singularity run \
                -B ${CONTAINER_DIR}:/resources \
                -B ${input_dir}:/data \
                -B ${work_dir}:/work \
                -B ${output_dir}:/output \
        ${CONTAINER_DIR}/${CONTAINER} /data /output \
        participant --participant_label $subject \
        -w /work \
        --no-sub \
        --nprocs 16 \
        --verbose-reports \
        --notrack \
        --session-id ${SESSION} \
        --omp-nthreads 4 \
        --write-graph