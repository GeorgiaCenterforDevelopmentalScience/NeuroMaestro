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

singularity run \
                -B ${CONTAINER_DIR}:/resources \
                -B ${input_dir}:/data \
                -B ${work_dir}:/work \
                -B ${output_dir}:/output \
        ${CONTAINER_DIR}/${CONTAINER} /data /output \
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