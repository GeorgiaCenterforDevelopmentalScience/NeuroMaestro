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

# resampled datasets are read via sub-brick selectors in the data table; keep them
# uncompressed so 3dLMEr doesn't pay the gzip decode cost on every read
export AFNI_COMPRESSOR=NONE
export OMP_NUM_THREADS="$JOBS"

# skip if the group result already exists
if [ -f "${OUTPUT_DIR}/emomatching_group_LMEr+tlrc.HEAD" ]; then
    echo "[skip] emomatching_group_LMEr already exists"
    exit 0
fi

# ---------------------------- Resample to common grid --------------------------------
# 3dLMEr requires all inputs on the same grid; align each subject's stats and brain mask
# to MASTER_FILE (stats: linear; mask: nearest-neighbour to stay 0/1)
MASTER_FILE="${INPUT_DIR}/${PREFIX}${MASTER_ID}/emomatching_output/${PREFIX}${MASTER_ID}.results/stats.${PREFIX}${MASTER_ID}_REML+tlrc"

for sub in "${SUB_IDS[@]}"; do
    subj="${PREFIX}${sub}"
    results_dir="${INPUT_DIR}/${subj}/emomatching_output/${subj}.results"
    orig_stats="${results_dir}/stats.${subj}_REML+tlrc"
    orig_mask="${results_dir}/full_mask.${subj}+tlrc"
    resamp_stats="${RESAMPLE_DIR}/stats.${subj}_REML+tlrc"
    resamp_mask="${RESAMPLE_DIR}/full_mask.${subj}+tlrc"

    if [ ! -f "${orig_stats}.HEAD" ]; then
        echo "  [missing source, skipping]: ${subj}"
        continue
    fi
    if [ ! -f "${resamp_stats}.HEAD" ]; then
        echo "  resampling: ${subj} ..."
        3dresample -master "$MASTER_FILE" -prefix "$resamp_stats" -inset "$orig_stats" >/dev/null 2>&1
    fi
    if [ -f "${orig_mask}.HEAD" ] && [ ! -f "${resamp_mask}.HEAD" ]; then
        3dresample -master "$MASTER_FILE" -rmode NN -prefix "$resamp_mask" -inset "$orig_mask" >/dev/null 2>&1
    fi
done
echo "resampling done"

# ------------------------------- Build the group mask --------------------------------
# intersection of the resampled subject masks; restricts the LME and the correction step
if [ ! -f "${GROUP_MASK}.HEAD" ]; then
    3dmask_tool -input "${RESAMPLE_DIR}"/full_mask.*+tlrc.HEAD -frac "${MASK_FRAC}" -prefix "$GROUP_MASK" >/dev/null 2>&1
fi

mask_opt=""
if [ -f "${GROUP_MASK}.HEAD" ]; then
    mask_opt="-mask ${GROUP_MASK}"
else
    echo "[warn] no group mask built; running without a mask"
fi

# ---------------------------- Build the data table -----------------------------------
# long format: one row per subject x condition, pointing at that condition's coef sub-brick

printf 'Subj\tcond\tInputFile\n' > "$TABLE_FILE"
for sub in "${SUB_IDS[@]}"; do
    subj="${PREFIX}${sub}"
    stats_file="${RESAMPLE_DIR}/stats.${subj}_REML+tlrc"
    if [ ! -f "${stats_file}.HEAD" ]; then
        echo "  [missing resampled stats, skipping]: ${subj}"
        continue
    fi
    for cond in "${CONDITIONS[@]}"; do
        idx=$(3dinfo -label2index "${cond}#0_Coef" "${stats_file}" 2>/dev/null)
        if [ -n "$idx" ]; then
            printf '%s\t%s\t%s\n' "${subj}" "${cond}" "${stats_file}[${idx}]" >> "$TABLE_FILE"
        else
            echo "  [no sub-brick '${cond}#0_Coef' for ${subj}, skipping this cell]"
        fi
    done
done

# abort if no valid subject/condition made it into the table
n_rows=$(( $(wc -l < "$TABLE_FILE") - 1 ))
if [ "$n_rows" -le 0 ]; then
    echo "[ERROR] data table is empty; no valid subject/condition found"
    exit 1
fi

# ------------------------------ Assemble GLTs from conditions ------------------------
# per-condition means, plus every pairwise contrast (covers custom weightings only if
# added by hand; for those, append extra -gltCode entries below)
glt_args=()
glt_labels=()
for c in "${CONDITIONS[@]}"; do
    glt_args+=( -gltCode "$c" "cond : 1*$c" )
    glt_labels+=( "$c" )
done
for ((i=0; i<${#CONDITIONS[@]}; i++)); do
    for ((j=i+1; j<${#CONDITIONS[@]}; j++)); do
        a=${CONDITIONS[i]}; b=${CONDITIONS[j]}
        glt_args+=( -gltCode "${a}-${b}" "cond : 1*$a -1*$b" )
        glt_labels+=( "${a}-${b}" )
    done
done

# ---------------------------------- Run 3dLMEr ---------------------------------------
# within-subject cond factor with a random intercept per subject; -resid feeds the correction

( cd "$OUTPUT_DIR" || exit
  3dLMEr -prefix emomatching_group_LMEr -jobs "$JOBS" $mask_opt  \
    -resid emomatching_group_LMEr_resid                          \
    -model 'cond+(1|Subj)'                                 \
    -SS_type 3                                             \
    "${glt_args[@]}"                                       \
    -dataTable @"$TABLE_FILE"
)

# ---------------------- Multiple-comparison correction -------------------------------
# 1) ACF smoothness from residuals  2) cluster-size threshold  3) apply to each GLT map

( cd "$OUTPUT_DIR" || exit
  3dFWHMx -acf acf_curve.1D $mask_opt -input emomatching_group_LMEr_resid+tlrc > acf_params.txt

  # a b c are the ACF model parameters on the last line of the 3dFWHMx output
  read -r acf_a acf_b acf_c _ <<< "$(tail -n 1 acf_params.txt)"

  # single pthr/athr -> the size comes out as one value; -nodec rounds it up to an integer
  3dClustSim -acf "$acf_a" "$acf_b" "$acf_c" $mask_opt \
    -pthr "$PTHR" -athr "$ATHR" -nodec -prefix clustsim
)

# cluster-size threshold (voxels) for the requested NN, bisided
CLUST_1D="${OUTPUT_DIR}/clustsim.NN${NN}_bisided.1D"
nvox=$(awk '!/^#/{print $2; exit}' "$CLUST_1D" 2>/dev/null)
if [ -z "$nvox" ]; then
    echo "[warn] could not read cluster size from $CLUST_1D; skipping 3dClusterize"
    exit 0
fi

# apply the voxelwise pthr (3dClusterize converts p->stat) + cluster size to each GLT
LMER_OUT="${OUTPUT_DIR}/emomatching_group_LMEr+tlrc"
for label in "${glt_labels[@]}"; do
    # 3dLMEr stores the effect in "<label>" and its z-statistic in "<label> Z"
    ithr=$(3dinfo -label2index "${label} Z" "$LMER_OUT" 2>/dev/null)
    if [ -z "$ithr" ]; then
        echo "  [no '${label} Z' stat sub-brick, skipping]"
        continue
    fi
    idat=$(3dinfo -label2index "${label}" "$LMER_OUT" 2>/dev/null)
    idat_opt=""
    [ -n "$idat" ] && idat_opt="-idat $idat -pref_dat clusters_${label}_dat.nii.gz"
    ( cd "$OUTPUT_DIR" || exit
      3dClusterize -inset "$LMER_OUT" -ithr "$ithr" $idat_opt $mask_opt -NN "$NN" \
        -bisided "p=$PTHR" -clust_nvox "$nvox"                                    \
        -pref_map "clusters_${label}.nii.gz" >/dev/null 2>&1
    )
    echo "  clusterized ${label}: ithr=${ithr}, p=${PTHR}, nvox>=${nvox}"
done
