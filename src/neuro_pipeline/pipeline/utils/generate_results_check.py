#!/usr/bin/env python3

import argparse
from pathlib import Path
from .config_utils import get_config_dir

RESULTS_CHECK_TEMPLATE = """\
# Results check configuration
# Keys must match task names defined in config.yaml

# Example — required_files check:
rest_preprocess:
  output_path: "{work_dir}/BIDS_derivatives/fmriprep/"
  required_files:
    - pattern: "sub-{subject}*.html"
      min_size_kb: 500

# Example — count_check:
recon:
  output_path: "{work_dir}/BIDS/sub-{subject}/ses-{session}/"
  count_check:
    anat:
      pattern: "anat/*.nii.gz"
      expected_count: 1
      tolerance: 0
"""


def generate_results_check(project_name: str, output_dir: str = None,
                           force: bool = False) -> Path:
    """Write a blank results-check template for project_name. Returns the output path."""
    out = Path(output_dir) if output_dir else get_config_dir() / "results_check"
    out.mkdir(parents=True, exist_ok=True)
    config_file = out / f"{project_name}_checks.yaml"

    if config_file.exists() and not force:
        raise FileExistsError(
            f"{config_file} already exists. Overwriting it would discard the "
            "check rules you have tuned for this project. Pass --force to replace it."
        )

    config_file.write_text(RESULTS_CHECK_TEMPLATE, encoding="utf-8")
    print(f"Results check template generated: {config_file}")
    return config_file


def main():
    parser = argparse.ArgumentParser(description="Generate a blank results-check config template")
    parser.add_argument("project_name", type=str, help="Project name (e.g., branch, study1)")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Output directory (default: config/results_check/)")
    args = parser.parse_args()
    generate_results_check(args.project_name, args.output_dir)


if __name__ == "__main__":
    main()
