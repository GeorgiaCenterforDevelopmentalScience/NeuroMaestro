#!/bin/bash

# Per-subject image-quality metrics via MRIQC.
# Task not restricted here (add `-t <task>` to limit); AFNI-based options like --deoblique
# are available (currently commented out).

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

# --nprocs below should track cpus_per_task in hpc_config.yaml.
# To follow it automatically, replace with:  --nprocs ${SLURM_CPUS_PER_TASK:-16} \
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