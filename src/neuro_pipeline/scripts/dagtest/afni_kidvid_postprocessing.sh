#!/bin/bash

# Group-level analysis: two-sample t-test (GroupA vs GroupB) per contrast.
# Resamples each subject (stats + brain mask) onto a common grid, builds a group mask,
# then runs 3dttest++ within that mask.

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

# Group membership (edit per project)
GroupA_IDS=(
    027 028
)

GroupB_IDS=(
    070 071
)

# split the space-joined env string back into an array
IFS=' ' read -ra CONTRASTS <<< "$CONTRASTS"

RESAMPLE_DIR="${OUTPUT_DIR}/resampled"

mkdir -p "$OUTPUT_DIR"
mkdir -p "$RESAMPLE_DIR"

# Reference grid for resampling: one subject's stats define the common grid
MASTER_FILE="${INPUT_DIR}/${PREFIX}${MASTER_ID}/ses-${SESSION}/kidvid_output/${PREFIX}${MASTER_ID}.results/stats.${PREFIX}${MASTER_ID}_REML+tlrc"
ALL_IDS=("${GroupA_IDS[@]}" "${GroupB_IDS[@]}")

# ---------------------------- Resample to common grid --------------------------------
# 3dttest++ requires all inputs on the same grid; align each subject to MASTER_FILE
for sub in "${ALL_IDS[@]}"; do
    results_dir="${INPUT_DIR}/${PREFIX}${sub}/ses-${SESSION}/kidvid_output/${PREFIX}${sub}.results"
    orig_file="${results_dir}/stats.${PREFIX}${sub}_REML+tlrc"
    orig_mask="${results_dir}/full_mask.${PREFIX}${sub}+tlrc"
    resamp_file="${RESAMPLE_DIR}/stats.${PREFIX}${sub}_REML+tlrc"
    resamp_mask="${RESAMPLE_DIR}/full_mask.${PREFIX}${sub}+tlrc"

    if [ ! -f "${orig_file}.HEAD" ]; then
        echo "  [missing source, skipping]: ${PREFIX}${sub}"
        continue
    fi
    if [ ! -f "${resamp_file}.HEAD" ]; then
        echo "  resampling: ${PREFIX}${sub} ..."
        3dresample -master "$MASTER_FILE" -prefix "$resamp_file" -inset "$orig_file" >/dev/null 2>&1
    fi
    if [ -f "${orig_mask}.HEAD" ] && [ ! -f "${resamp_mask}.HEAD" ]; then
        3dresample -master "$MASTER_FILE" -rmode NN -prefix "$resamp_mask" -inset "$orig_mask" >/dev/null 2>&1
    fi
done
echo "resampling done"

# ------------------------------- Build the group mask --------------------------------
# intersection of the resampled subject masks; restricts 3dttest++ (including its Clustsim)
GROUP_MASK="${OUTPUT_DIR}/group_mask+tlrc"
if [ ! -f "${GROUP_MASK}.HEAD" ]; then
    3dmask_tool -input "${RESAMPLE_DIR}"/full_mask.*+tlrc.HEAD -frac 1.0 -prefix "$GROUP_MASK" >/dev/null 2>&1
fi

mask_opt=""
if [ -f "${GROUP_MASK}.HEAD" ]; then
    mask_opt="-mask ${GROUP_MASK}"
else
    echo "[warn] no group mask built; running without a mask"
fi

# ---------------------------------- Group comparison ---------------------------------

# For each contrast, gen_group_command.py assembles the 3dttest++ command (it handles
# -setA/-setB and the sub-brick selection), then we run the generated script.

for contrast in "${CONTRASTS[@]}"; do
    out_prefix="Stats_GroupA_vs_GroupB_${contrast}"
    echo "processing: ${contrast}"

    if [ -f "${OUTPUT_DIR}/${out_prefix}+tlrc.HEAD" ]; then
        echo "  [skip]"
        continue
    fi

    # existing resampled datasets in each group
    setA_dsets=()
    for sub in "${GroupA_IDS[@]}"; do
        f="${RESAMPLE_DIR}/stats.${PREFIX}${sub}_REML+tlrc"
        [ -f "${f}.HEAD" ] && setA_dsets+=( "$f" )
    done
    setB_dsets=()
    for sub in "${GroupB_IDS[@]}"; do
        f="${RESAMPLE_DIR}/stats.${PREFIX}${sub}_REML+tlrc"
        [ -f "${f}.HEAD" ] && setB_dsets+=( "$f" )
    done

    if [ ${#setA_dsets[@]} -eq 0 ] || [ ${#setB_dsets[@]} -eq 0 ]; then
        echo "  [skip] not enough subjects (GroupA: ${#setA_dsets[@]}, GroupB: ${#setB_dsets[@]})"
        continue
    fi

    # build the 3dttest++ command, then run it. -subs_betas picks the contrast's coef
    # sub-brick; -options passes the rest through to 3dttest++.
    # to control for nuisance variables, add to -options: -covariates cov.1D -center DIFF
    cmd_script="${OUTPUT_DIR}/cmd.3dttest++.${contrast}"
    gen_group_command.py -command 3dttest++            \
        -write_script "$cmd_script"                    \
        -prefix "${OUTPUT_DIR}/${out_prefix}"          \
        -dsets "${setA_dsets[@]}"                       \
        -dsets "${setB_dsets[@]}"                       \
        -set_labels GroupA GroupB                                 \
        -subs_betas "${contrast}#0_Coef" "${contrast}#0_Coef"     \
        -options $mask_opt -Clustsim "$CLUSTSIM"

    tcsh "$cmd_script"
    echo "  done (GroupA: ${#setA_dsets[@]}, GroupB: ${#setB_dsets[@]})"
done

# TODO: cluster-level correction (3dClusterize) not implemented here yet.
# 3dttest++ -Clustsim already packs cluster-size thresholds into the output header (via
# 3drefit), so the third step should read those and run 3dClusterize per contrast, rather
# than re-running 3dFWHMx/3dClustSim. Notes for whoever implements it:
#   - -Clustsim auto-enables -toz, so the stat sub-brick is a z-score (label like
#     "GroupA-GroupB_Zscr"), not a t-stat.
#   - pull the cluster size from the embedded table with
#     1d_tool.py -csim_pthr <p> -csim_alpha <a>  (or read the .1D that -Clustsim writes).
# Align the extraction with the existing project script before implementing.
# See afni_cards_postprocessing.sh for the 3dLMEr-side equivalent.
