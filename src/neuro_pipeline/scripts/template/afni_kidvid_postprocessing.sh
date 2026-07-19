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

# For each contrast, assemble the two groups' "label dataset[coef]" pairs and run 3dttest++.

for contrast in "${CONTRASTS[@]}"; do
    out_prefix="Stats_GroupA_vs_GroupB_${contrast}"
    echo "processing: ${contrast}"

    if [ -f "${OUTPUT_DIR}/${out_prefix}+tlrc.HEAD" ]; then
        echo "  [skip]"
        continue
    fi

    # "label dataset[coef]" pairs per group (label selector, no 3dinfo needed)
    setA_args=()
    for sub in "${GroupA_IDS[@]}"; do
        f="${RESAMPLE_DIR}/stats.${PREFIX}${sub}_REML+tlrc"
        [ -f "${f}.HEAD" ] && setA_args+=( "${PREFIX}${sub}" "${f}[${contrast}#0_Coef]" )
    done

    setB_args=()
    for sub in "${GroupB_IDS[@]}"; do
        f="${RESAMPLE_DIR}/stats.${PREFIX}${sub}_REML+tlrc"
        [ -f "${f}.HEAD" ] && setB_args+=( "${PREFIX}${sub}" "${f}[${contrast}#0_Coef]" )
    done

    if [ ${#setA_args[@]} -eq 0 ] || [ ${#setB_args[@]} -eq 0 ]; then
        echo "  [skip] not enough subjects (GroupA: $(( ${#setA_args[@]} / 2 )), GroupB: $(( ${#setB_args[@]} / 2 )))"
        continue
    fi

    # relative -prefix + cd: 3dttest++ -Clustsim rejects an absolute -prefix.
    # to control for nuisance variables, add: -covariates cov.1D -center DIFF
    ( cd "$OUTPUT_DIR" && 3dttest++ -prefix "$out_prefix" $mask_opt -AminusB \
        -setA GroupA "${setA_args[@]}"                                       \
        -setB GroupB "${setB_args[@]}"                                       \
        -Clustsim "$CLUSTSIM" )

    echo "  done (GroupA: $(( ${#setA_args[@]} / 2 )), GroupB: $(( ${#setB_args[@]} / 2 )))"
done

# ---------------------- Multiple-comparison correction -------------------------------
# 3dttest++ -Clustsim already computed per-contrast cluster tables (.CSimA .1D + embedded
# header attrs); look up the size for (PTHR, ATHR) and apply 3dClusterize to each stat
# sub-brick. -Clustsim auto-enables -toz, so the stat is "<base>_Zscr" and the effect
# estimate is "<base>_mean".
for contrast in "${CONTRASTS[@]}"; do
    out_prefix="Stats_GroupA_vs_GroupB_${contrast}"
    dset="${OUTPUT_DIR}/${out_prefix}+tlrc"
    csim_1d="${OUTPUT_DIR}/${out_prefix}.CSimA.NN${NN}_bisided.1D"

    # skip contrasts with no result or no embedded clustsim table
    [ -f "${dset}.HEAD" ] || continue
    if [ ! -f "$csim_1d" ]; then
        echo "  [no clustsim table for ${contrast}, skipping correction]"
        continue
    fi

    # cluster-size threshold (voxels) for this (PTHR, ATHR) from the embedded table
    nvox=$(1d_tool.py -infile "$csim_1d" -csim_pthr "$PTHR" -csim_alpha "$ATHR" \
                      -csim_show_clustsize -verb 0 2>/dev/null | tail -n 1)
    if [ -z "$nvox" ]; then
        echo "  [could not read cluster size for ${contrast}, skipping]"
        continue
    fi

    # threshold each stat sub-brick (between-group + each group) and keep surviving clusters
    for base in GroupA-GroupB GroupA GroupB; do
    
        # ithr: z-stat sub-brick to threshold on; idat: matching effect (mean) to report
        ithr=$(3dinfo -label2index "${base}_Zscr" "$dset" 2>/dev/null)
        [ -z "$ithr" ] && { echo "  [no '${base}_Zscr' in ${contrast}, skipping]"; continue; }

        idat=$(3dinfo -label2index "${base}_mean" "$dset" 2>/dev/null)
        idat_opt=""
        [ -n "$idat" ] && idat_opt="-idat $idat -pref_dat clusters_${contrast}_${base}_dat.nii.gz"

        # voxelwise p=PTHR (bisided) + cluster size -> surviving-cluster map
        ( cd "$OUTPUT_DIR" || exit
          3dClusterize -inset "$dset" -ithr "$ithr" $idat_opt $mask_opt -NN "$NN" \
            -bisided "p=$PTHR" -clust_nvox "$nvox"                                \
            -pref_map "clusters_${contrast}_${base}.nii.gz" >/dev/null 2>&1
        )
        echo "  clusterized ${contrast}/${base}: ithr=${ithr}, p=${PTHR}, nvox>=${nvox}"
    done
done
