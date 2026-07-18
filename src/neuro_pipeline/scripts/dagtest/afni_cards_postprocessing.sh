#!/bin/bash

# Group-level analysis: single-group LME (3dLMEr) over the within-subject cond factor (BW/BL).
# Resamples each subject to a common grid, builds a long-format data table, runs 3dLMEr,
# then estimates a cluster-size threshold for multiple-comparison correction.

# ---------------------------------- Setup ---------------------------------------------

echo "Input directory: $INPUT_DIR"
echo "Output directory: $OUTPUT_DIR"
echo "Prefix: $PREFIX"
echo "Session: $SESSION"
echo "Subjects: $SUBJECTS"

# within-subject conditions; the coef sub-brick is looked up as "<cond>#0_Coef"
CONDITIONS=(BW BL)

IFS=' ' read -ra SUB_IDS <<< "$SUBJECTS"

RESAMPLE_DIR="${OUTPUT_DIR}/resampled"

mkdir -p "$OUTPUT_DIR"
mkdir -p "$RESAMPLE_DIR"

TABLE_FILE="${OUTPUT_DIR}/lme_datatable.txt"

# skip if the group result already exists
if [ -f "${OUTPUT_DIR}/cards_group_LMEr+tlrc.HEAD" ]; then
    echo "[skip] cards_group_LMEr already exists"
    exit 0
fi

# ---------------------------- Resample to common grid --------------------------------
# 3dLMEr requires all inputs on the same grid; align each subject to MASTER_FILE
MASTER_FILE="${INPUT_DIR}/${PREFIX}${MASTER_ID}/ses-${SESSION}/cards_output/${PREFIX}${MASTER_ID}.results/stats.${PREFIX}${MASTER_ID}_REML+tlrc"

for sub in "${SUB_IDS[@]}"; do
    orig_file="${INPUT_DIR}/${PREFIX}${sub}/ses-${SESSION}/cards_output/${PREFIX}${sub}.results/stats.${PREFIX}${sub}_REML+tlrc"
    resamp_file="${RESAMPLE_DIR}/stats.${PREFIX}${sub}_REML+tlrc"

    if [ ! -f "${orig_file}.HEAD" ]; then
        echo "  [missing source, skipping]: ${PREFIX}${sub}"
        continue
    fi
    if [ ! -f "${resamp_file}.HEAD" ]; then
        echo "  resampling: ${PREFIX}${sub} ..."
        3dresample -master "$MASTER_FILE" -prefix "$resamp_file" -inset "$orig_file" >/dev/null 2>&1
    fi
done
echo "resampling done"

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

# ---------------------------------- Run 3dLMEr ---------------------------------------
# model: within-subject cond factor with a random intercept per subject
# GLTs: each condition mean, plus the BW-BL contrast
# -resid writes residuals, used below to estimate smoothness for the correction step

( cd "$OUTPUT_DIR" || exit
  3dLMEr -prefix cards_group_LMEr -jobs 8              \
    -resid cards_group_LMEr_resid                      \
    -model 'cond+(1|Subj)'                             \
    -gltCode BW    'cond : 1*BW'                       \
    -gltCode BL    'cond : 1*BL'                       \
    -gltCode BW-BL 'cond : 1*BW -1*BL'                 \
    -dataTable @"$TABLE_FILE"
)

# ---------------------- Multiple-comparison correction (sample step) ------------------
# estimate ACF smoothness from the residuals, then derive cluster-size thresholds.
# For real analyses, pass a group mask to both tools (-mask) and tune -jobs.

( cd "$OUTPUT_DIR" || exit
  3dFWHMx -acf acf_curve.1D -input cards_group_LMEr_resid+tlrc > acf_params.txt

  # a b c are the ACF model parameters on the last line of the 3dFWHMx output
  read -r acf_a acf_b acf_c _ <<< "$(tail -n 1 acf_params.txt)"

  3dClustSim -acf "$acf_a" "$acf_b" "$acf_c" -jobs 8 -prefix clustsim
)
