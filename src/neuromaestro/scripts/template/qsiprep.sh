#!/bin/bash

# DWI preprocessing via QSIPrep.
# Needs a FreeSurfer license. --use-syn-sdc / --force-syn force fieldmap-less SyN
# distortion correction (SDC).

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

# --nthreads below should track cpus_per_task in hpc_config.yaml.
# To follow it automatically, replace with:  --nthreads ${SLURM_CPUS_PER_TASK:-16} \
singularity run \
                -B ${CONTAINER_DIR}:/resources \
                -B ${INPUT_DIR}:/data \
                -B ${work_dir}:/work \
                -B ${OUTPUT_DIR}:/output \
                -B ${FREESURFER_DIR}:/freesurfer \
        ${CONTAINER_DIR}/${CONTAINER} /data /output \
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
