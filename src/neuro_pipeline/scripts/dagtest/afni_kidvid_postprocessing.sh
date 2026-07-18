#!/bin/bash

# Group-level analysis: two-sample t-test (GroupA vs GroupB) per contrast.
# Resamples each subject (stats + brain mask) onto a common grid, builds a group mask,
# then runs 3dttest++ within that mask.

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

# build_set(array_name, contrast): scan one group's subjects and, for each one that has a
# valid coefficient, collect a "label dataset[idx]" pair for 3dttest++.
# Results are returned via the globals $args (the pairs) and $count (number of subjects);
# the caller must snapshot them before the next call overwrites them.
build_set() {
    local -n _ids=$1              # nameref: $1 is the caller's array name, not its value
    local contrast=$2
    args=()                       # accumulated "label dataset[idx]" pairs
    count=0                       # number of subjects actually added
    for sub in "${_ids[@]}"; do
        # resampled stats dataset for this subject
        f="${RESAMPLE_DIR}/stats.${PREFIX}${sub}_REML+tlrc"
        if [ -f "${f}.HEAD" ]; then                 # skip subjects with no resampled file
            # sub-brick index of this contrast's coefficient (position varies per subject)
            idx=$(3dinfo -label2index "${contrast}#0_Coef" "${f}" 2>/dev/null)
            if [ -n "$idx" ]; then                  # contrast present in this dataset
                args+=( "${PREFIX}${sub}" "${f}[${idx}]" )   # label, then dataset[sub-brick]
                ((count++))
            fi
        fi
    done
}

for contrast in "${CONTRASTS[@]}"; do
    # resolve output paths; skip the contrast if both formats already exist
    out_file="$OUTPUT_DIR/Stats_GroupA_vs_GroupB_${contrast}.nii.gz"
    afni_head="$OUTPUT_DIR/Stats_GroupA_vs_GroupB_${contrast}+tlrc.HEAD"

    echo "processing: ${contrast}"

    if [ -f "$out_file" ] && [ -f "$afni_head" ]; then
        echo "  [skip]"
        continue
    fi

    # collect each group's datasets (snapshot right away; build_set reuses $args/$count)
    build_set GroupA_IDS "$contrast"; setA_args=("${args[@]}"); count_a=$count
    build_set GroupB_IDS "$contrast"; setB_args=("${args[@]}"); count_b=$count

    echo "  GroupA args: ${setA_args[@]}"
    echo "  GroupB args: ${setB_args[@]}"

    # both groups need at least one valid subject
    if [ "$count_a" -eq 0 ] || [ "$count_b" -eq 0 ]; then
        echo "  [skip] not enough subjects (GroupA: $count_a, GroupB: $count_b)"
        continue
    fi

    # two-sample test: GroupA minus GroupB
    # to control for nuisance variables, add e.g.: -covariates cov.1D -center DIFF
    if [ ! -f "$out_file" ]; then
        ( cd "$OUTPUT_DIR" || exit
          3dttest++                                                    \
            -prefix  "Stats_GroupA_vs_GroupB_${contrast}.nii.gz"     \
            $mask_opt                                                  \
            -AminusB                                                   \
            -setA GroupA "${setA_args[@]}"                            \
            -setB GroupB "${setB_args[@]}"                            \
            -Clustsim "$CLUSTSIM"
        )
    fi

    # emit an AFNI +tlrc copy of the NIfTI result for downstream AFNI tools
    if [ ! -f "$afni_head" ]; then
        ( cd "$OUTPUT_DIR" || exit
          3dcopy "Stats_GroupA_vs_GroupB_${contrast}.nii.gz" "Stats_GroupA_vs_GroupB_${contrast}+tlrc" >/dev/null 2>&1
        )
    fi

    echo "  done (GroupA: $count_a, GroupB: $count_b)"
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
