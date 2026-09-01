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
        -vv \
        --dry-run
