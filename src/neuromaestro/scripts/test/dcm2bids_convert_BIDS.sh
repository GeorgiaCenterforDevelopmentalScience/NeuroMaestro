#!/bin/bash

# ---------------------------------- Setup ---------------------------------------------

# You need a folder with a file name that includes the subject ID. The program cannot extract ID for you.
# config.json file is also required, it will decide what naming pattern you want.

subject="$1"
echo "Processing subject: $subject for BIDS reconstruction"

prefix="$PREFIX"
session="$SESSION"

input_dir="$INPUT_DIR/ses-${SESSION}/${prefix}${subject}"
output_dir="$OUTPUT_DIR"
work_dir="$WORK_DIR"


mkdir -p "$output_dir"
mkdir -p "$work_dir"

echo "Input directory: $input_dir"
echo "Output directory: $output_dir"
echo "Work directory: $work_dir"

# ---------------------------------- Run Processing -------------------------------------

singularity run \
                -e --containall \
                -B ${input_dir}:/dicoms:ro \
                -B ${CONFIG_DIR}/${CONFIG}:/config.json:ro \
                -B ${output_dir}:/bids \
  ${CONTAINER_DIR}/${CONTAINER} \
  -o /bids \
  -d /dicoms \
  -c /config.json \
  --force_dcm2bids \
  --auto_extract_entities \
  -p ${subject} \
  -s ${session} \
  --clobber

  # --bids_validate \

# ---------------------------------- BIDS Metadata -------------------------------------

# Create dataset_description.json only if it doesn't exist
if [ ! -f "$output_dir/dataset_description.json" ]; then
  cat <<EOF > "$output_dir/dataset_description.json"
{
  "Name": "${PROJECT}",
  "BIDSVersion": "1.6.0",
  "DatasetType": "raw"
}
EOF
  echo " Created dataset_description.json"
else
  echo " dataset_description.json already exists. Skipping creation."
fi

# Recreate participants.tsv every time for safety
echo -e "participant_id\tsex\tage" > "$output_dir/participants.tsv"

for subj_dir in "$output_dir"/sub-*; do
  if [ -d "$subj_dir" ]; then
    subj_id=$(basename "$subj_dir")
    echo -e "${subj_id}\tn/a\tn/a" >> "$output_dir/participants.tsv"
  fi
done

echo " Updated participants.tsv"

# mkdir -p $work_dir/BIDS/tmp_dcm2bids
# mkdir -p $work_dir/BIDS/tmp_dcm2bids/log

# mv $output_dir/tmp_dcm2bids/sub-${subject}_ses-${session} $work_dir/BIDS/tmp_dcm2bids
# mv $output_dir/tmp_dcm2bids/log/sub-${subject}_ses-${session}* $work_dir/BIDS/tmp_dcm2bids/log
