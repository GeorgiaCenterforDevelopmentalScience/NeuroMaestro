#!/bin/bash

# Group-level analysis: two-sample t-test (GroupA vs GroupB) per contrast.
# Resamples each subject (stats + brain mask) onto a common grid, builds a group mask,
# runs 3dttest++ (with -Clustsim) within that mask, then applies cluster-level correction
# (3dClusterize) to each stat sub-brick.
# CONTRASTS lists which per-condition coef maps to test between groups (one 3dttest++ per
# entry); it does NOT form condition-vs-condition contrasts.

# https://afni.nimh.nih.gov/pub/dist/doc/htmldoc/programs/alpha/gen_group_command.py_sphx.html#ahelp-gen-group-command-py
# https://afni.nimh.nih.gov/pub/dist/doc/htmldoc/programs/alpha/3dttest%2B%2B_sphx.html#ahelp-3dttest
# https://afni.nimh.nih.gov/pub/dist/doc/htmldoc/programs/alpha/3dClustSim_sphx.html#ahelp-3dclustsim
# https://afni.nimh.nih.gov/pub/dist/doc/htmldoc/programs/alpha/3dClusterize_sphx.html#ahelp-3dclusterize

# ---------------------------------- Setup ---------------------------------------------

echo "Input directory: $INPUT_DIR"
echo "Output directory: $OUTPUT_DIR"
echo "Prefix: $PREFIX"
echo "Session: $SESSION"
echo "Contrasts: $CONTRASTS"
echo "Master subject: $MASTER_ID"
echo "Clustsim: $CLUSTSIM"
echo "Pthr: $PTHR"
echo "Athr: $ATHR"
echo "NN: $NN"

# Group membership (edit per project)
GroupA_IDS=(
    027 028
)

GroupB_IDS=(
    070 071
)