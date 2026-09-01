#!/bin/bash

echo "Input directory: $INPUT_DIR"
echo "Output directory: $OUTPUT_DIR"

# IFS=' ' read -ra SUB_IDS <<< "$1"

# CONTRAST="Inc-Con"
# BRICK_IDX=7

# mkdir -p "$OUTPUT_DIR"

# setA_args=()
# count=0
# for sub in "${SUB_IDS[@]}"; do
#     f="${INPUT_DIR}/${PREFIX}${sub}/${PREFIX}${sub}.results/stats.${PREFIX}${sub}_REML+tlrc"
#     if [ -f "${f}.HEAD" ]; then
#         setA_args+=( "${PREFIX}${sub}" "${f}[${BRICK_IDX}]" )
#         ((count++)) || true
#     else
#         echo "  [missing, skipping]: ${PREFIX}${sub}"
#     fi
# done

# echo "setA args: ${setA_args[@]}"
# echo "n subjects: $count"

# ( cd "$OUTPUT_DIR" || exit
#   3dttest++                               \
#     -prefix  "${CONTRAST}_group"          \
#     -mask    "$MASK_FILE"                 \
#     -setA    "$CONTRAST" "${setA_args[@]}"
# )
