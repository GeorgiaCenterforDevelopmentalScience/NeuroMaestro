#!/bin/bash

# Group-level analysis: single-group LME (3dLMEr) over the within-subject cond factor.
# Resamples each subject (stats + brain mask) to a common grid, builds a group mask and a
# long-format data table, runs 3dLMEr, then applies cluster-level correction
# (3dFWHMx -> 3dClustSim -> 3dClusterize) within the mask.
# CONDITIONS are the LME factor levels; the script auto-builds per-condition means plus
# every pairwise within-subject contrast.

# https://afni.nimh.nih.gov/pub/dist/doc/htmldoc/programs/alpha/3dLMEr_sphx.html#ahelp-3dlmer

# ---------------------------------- Setup ---------------------------------------------

echo "Input directory: $INPUT_DIR"
echo "Output directory: $OUTPUT_DIR"
echo "Prefix: $PREFIX"
echo "Session: $SESSION"
echo "Subjects: $SUBJECTS"
echo "Conditions: $CONDITIONS"
echo "Master subject: $MASTER_ID"
echo "Jobs: $JOBS"

# split the space-joined env strings back into arrays
IFS=' ' read -ra CONDITIONS <<< "$CONDITIONS"
IFS=' ' read -ra SUB_IDS <<< "$SUBJECTS"

RESAMPLE_DIR="${OUTPUT_DIR}/resampled"
GROUP_MASK="${OUTPUT_DIR}/group_mask+tlrc"
TABLE_FILE="${OUTPUT_DIR}/lme_datatable.txt"

mkdir -p "$OUTPUT_DIR"
mkdir -p "$RESAMPLE_DIR"