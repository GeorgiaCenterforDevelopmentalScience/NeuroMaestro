---
title: Output Checks Configuration
---

# Output Checks Configuration

The output checks system serves two purposes:

1. **`--resume`**: before submitting each task's SLURM array job, the pipeline checks which subjects already have valid outputs and silently excludes them from the submission. Checks are scoped to the tasks you explicitly request on the command line; tasks not included in the current invocation are not evaluated, even if they are configured in the YAML or have failed previously.
2. **`neuromaestro check-outputs`**: a standalone command that runs the same checks on demand and saves a CSV report.

Both use the same YAML configuration file.

## Configuration File Location

```
config/results_check/{project}_checks.yaml
```

The file is named after your project (same as your `{project}_config.yaml`). For example, project `branch` → `branch_checks.yaml`.

Generate a blank template with the CLI or the GUI:

```bash
neuromaestro generate-checks branch
```

Or open the **Results Check Config** tab in the GUI and click **New**.

After generating, edit the file to add your task checks, then save it back via the GUI **Save** button or directly on disk.

If the file doesn't exist when you run `--resume`, a warning is printed and all subjects are submitted for every task:

```
Warning: Output checks config not found: .../branch_checks.yaml
         Create 'branch_checks.yaml' in .../results_check to enable resume.
```

## File Structure

```yaml
# Each top-level key is a task name (must match config.yaml exactly)
task_name:
  output_path: "{work_dir}/path/to/{prefix}{subject}/ses-{session}/"

  # Check type 1: specific files must exist
  required_files:
    - pattern: "filename_or_glob"
      min_size_kb: 500        # optional

  # Check type 2: file count within expected ± tolerance
  count_check:
    label:                    # arbitrary label for this check
      pattern: "*.nii.gz"
      expected_count: 4
      tolerance: 1
```

Both check types are optional and can be combined freely within one task.

## Path Placeholders

The `output_path` and `pattern` fields support these placeholders:

| Placeholder | Expands to | Example |
|-------------|-----------|---------|
| `{work_dir}` | The directory that **directly contains** `BIDS/`, `AFNI_derivatives/`, `BIDS_derivatives/`, `quality_control/` (i.e. your `run` `--output` directory with the project name appended) | `/data/processed/branch` |
| `{subject}` | Subject ID without prefix | `001` |
| `{prefix}` | Subject directory prefix | `sub-` |
| `{session}` | Session label | `01` |

`output_path` is the base directory. Patterns are joined to it with `os.path.join` before globbing, so they are relative to `output_path`.

:::{important}
`{work_dir}` is whatever you pass to `check-outputs --work`. Every `output_path` is built relative to it (`{work_dir}/BIDS/...`, `{work_dir}/AFNI_derivatives/...`), so `--work` must point at the folder that holds those subdirectories, **not** the `run` `--work` directory that holds logs and the database. If the path is one level off (e.g. you pass `.../BIDS/branch/BIDS/work`), every glob resolves under a non-existent directory and all checks report `FAIL: file not found`. Under `--resume` the same value is supplied automatically as `run --output` plus the project name, so it always matches the tree the jobs write to and needs no separate configuration. Confirm your path first:

```bash
# Should list BIDS  AFNI_derivatives  BIDS_derivatives  quality_control
ls <your --work path>
```
:::

## Check Type: `required_files`

Each entry in the list must resolve to at least one existing file.

```yaml
volume:
  output_path: "{work_dir}/AFNI_derivatives/{prefix}{subject}/ses-{session}/sswarp2/T1_results"
  required_files:
    - pattern: "QC_anatSS.{prefix}{subject}.jpg"
      min_size_kb: 50
```

**Logic:**

1. The pattern is expanded with `{subject}`, `{prefix}`, `{session}` placeholders.
2. The expanded pattern is globbed against `output_path/pattern` (recursive glob supported with `**`).
3. If no files match → **FAIL** (`file not found`).
4. If `min_size_kb` is set and all matching files are smaller than the threshold → **FAIL** (`file exists but too small`).
5. Otherwise → **PASS**.

Plain strings (without `min_size_kb`) are also accepted:

```yaml
required_files:
  - "sub-{subject}*.html"           # shorthand — no size check
  - pattern: "stats+tlrc.HEAD"
    min_size_kb: 1000               # with size check
```

## Check Type: `count_check`

Validates that a glob matches a specific number of files, within a tolerance.

```yaml
recon:
  output_path: "{work_dir}/BIDS/sub-{subject}/ses-{session}/"
  count_check:
    anat:
      pattern: "anat/*.nii.gz"
      expected_count: 1
      tolerance: 0
    rest:
      pattern: "func/*rest*.nii.gz"
      expected_count: 2
      tolerance: 1
    fmap:
      pattern: "fmap/*.nii.gz"
      expected_count: 4
      tolerance: 1
```

**Logic:**

- `actual` = number of files matching `output_path/pattern`
- `|actual − expected_count| ≤ tolerance` → **PASS**
- `actual > expected_count + tolerance` → **FAIL** (`too many files`)
- `actual < expected_count − tolerance` → **FAIL** (`too few files`)

The label (e.g. `anat`, `rest`, `fmap`) is arbitrary; it appears in the CSV report as `check_type: count_check:anat`.

## Full Example: Real Project Checks

This is the checks file used by the BRANCH study:

:::{dropdown} View full example config branch_checks.yaml
```yaml
# Prep
recon:
  output_path: "{work_dir}/BIDS/sub-{subject}/ses-{session}/"
  count_check:
    anat:
      pattern: "anat/*.nii.gz"
      expected_count: 1
      tolerance: 0
    fmap:
      pattern: "fmap/*.nii.gz"
      expected_count: 4
      tolerance: 1
    rest:
      pattern: "func/*rest*.nii.gz"
      expected_count: 2
      tolerance: 1
    kidvid:
      pattern: "func/*kidvid*.nii.gz"
      expected_count: 1
      tolerance: 0
    cards:
      pattern: "func/*cards*.nii.gz"
      expected_count: 1
      tolerance: 0
    dwi:
      pattern: "dwi/*.nii.gz"
      expected_count: 1
      tolerance: 0

# Intermed
volume:
  output_path: "{work_dir}/AFNI_derivatives/{prefix}{subject}/ses-{session}/sswarp2/T1_results"
  required_files:
    - pattern: "QC_anatSS.{prefix}{subject}.jpg"
      min_size_kb: 50

# Resting-state fMRI
rest_preprocess:
  output_path: "{work_dir}/BIDS_derivatives/fmriprep/"
  required_files:
    - pattern: "sub-{subject}*.html"
      min_size_kb: 500

rest_post:
  output_path: "{work_dir}/BIDS_derivatives/xcpd/sub-{subject}/ses-{session}"
  required_files:
    - pattern: "sub-{subject}*.html"
      min_size_kb: 200

# Task fMRI
cards_preprocess:
  output_path: "{work_dir}/AFNI_derivatives/{prefix}{subject}/ses-{session}/cards_output/{prefix}{subject}.results/QC_{prefix}{subject}"
  required_files:
    - pattern: "index.html"
      min_size_kb: 50

kidvid_preprocess:
  output_path: "{work_dir}/AFNI_derivatives/{prefix}{subject}/ses-{session}/kidvid_output/{prefix}{subject}.results/QC_{prefix}{subject}"
  required_files:
    - pattern: "index.html"
      min_size_kb: 50

# DWI
dwi_preprocess:
  output_path: "{work_dir}/BIDS_derivatives/qsiprep"
  required_files:
    - pattern: "sub-{subject}*.html"
      min_size_kb: 200

dwi_post:
  output_path: "{work_dir}/BIDS_derivatives/qsirecon"
  required_files:
    - pattern: "sub-{subject}*.html"
      min_size_kb: 200

# Quality control
mriqc_preprocess:
  output_path: "{work_dir}/quality_control/mriqc"
  required_files:
    - pattern: "sub-{subject}*.html"
      min_size_kb: 100

mriqc_post:
  output_path: "{work_dir}/quality_control/mriqc"
  required_files:
    - pattern: "group_*.html"
      min_size_kb: 50
```
:::

## How a Subject's Status Is Determined

A subject is **COMPLETE** for a task if and only if **every check item** in that task's config returns PASS. A single failure in any check marks the subject as pending.

```
subject 001 on task rest_preprocess:
  required_files[0]: sub-001*.html  → PASS (file exists, 620 KB ≥ 500 KB)
  → ALL PASS → subject is COMPLETE → excluded from --resume submission

subject 002 on task rest_preprocess:
  required_files[0]: sub-002*.html  → FAIL (file not found)
  → ANY FAIL → subject is PENDING → included in --resume submission
```

If a task has **no entry** in the checks YAML, `get_completed_subjects` returns an empty list (no one is considered complete), so `get_pending_subjects` returns **all subjects**: everyone is treated as pending and the full subject list is submitted. A warning is printed. The resume flag has no effect for that task.

## `neuromaestro check-outputs` Command

Run checks independently of a pipeline submission:

```bash
neuromaestro check-outputs \
  --project my_study \
  --work /data/processed/my_study \
  --config-dir /data/config \
  --session 01 \
  --subjects 001,002,003,004,005
```

`--work` is the base for `{work_dir}` in the checks YAML: it must be the folder that directly contains `BIDS/`, `AFNI_derivatives/`, etc. (your `run` `--output` directory with the project name appended), not the `run` `--work` log/database directory.

`--session` is required. It is written into every CSV row, which is what lets you attribute a failure to a session later. Pass several at once with a comma (`--session 01,02`); each is checked in turn and the results go into a single CSV. If your checks YAML has no `{session}` placeholder (a project without sessions), pass any value: it is accepted and simply unused when the paths are built.

### Optional filters

```bash
# Check only specific tasks
neuromaestro check-outputs \
  --project my_study \
  --work /data/work \
  --config-dir /data/config \
  --session 01 \
  --subjects 001,002,003 \
  --task rest_preprocess

# Point to a non-default checks file
neuromaestro check-outputs \
  --project my_study \
  --work /data/work \
  --config-dir /data/config \
  --session 01 \
  --subjects 001,002,003 \
  --checks-dir /path/to/custom/checks/
```

### Output

The command prints a terminal summary and saves a full CSV report:

```
[check-outputs] Issues found:
  rest_preprocess: 002, 004
  volume: 004
```

The CSV is written to `{work_dir}/check_results_{timestamp}.csv` with one row per check item:

| Column | Description |
|--------|-------------|
| `task` | Task name |
| `subject` | Subject ID |
| `session` | Session label |
| `check_type` | `required_files` or `count_check:{label}` |
| `pattern` | The glob pattern that was evaluated |
| `expected` | `exists`, `exists + ≥N KB`, or `N±tolerance` |
| `actual` | Number of files found |
| `status` | `PASS` or `FAIL: reason` |

Example output (3 subjects, 2 tasks):

| task | subject | session | check_type | pattern | expected | actual | status |
|------|---------|---------|------------|---------|----------|--------|--------|
| rest_preprocess | 001 | 01 | required_files | sub-{subject}*.html | exists + ≥500 KB | 1 | PASS |
| rest_preprocess | 002 | 01 | required_files | sub-{subject}*.html | exists + ≥500 KB | 0 | FAIL: file not found |
| rest_preprocess | 003 | 01 | required_files | sub-{subject}*.html | exists + ≥500 KB | 1 | FAIL: file exists but too small (< 500 KB) |
| recon | 001 | 01 | count_check:anat | anat/*.nii.gz | 1±0 | 1 | PASS |
| recon | 001 | 01 | count_check:fmap | fmap/*.nii.gz | 4±1 | 4 | PASS |
| recon | 002 | 01 | count_check:anat | anat/*.nii.gz | 1±0 | 1 | PASS |
| recon | 002 | 01 | count_check:fmap | fmap/*.nii.gz | 4±1 | 2 | FAIL: too few files on fmap (got 2, expected 4±1) |
| recon | 003 | 01 | count_check:anat | anat/*.nii.gz | 1±0 | 1 | PASS |
| recon | 003 | 01 | count_check:fmap | fmap/*.nii.gz | 4±1 | 5 | PASS |

The terminal summary only shows which subjects failed, not why. Open the CSV for the per-check detail.

## Tips

**Using `**` for recursive search:**

```yaml
required_files:
  - pattern: "**/sub-{subject}*space-T1w_boldref.nii.gz"
```

**Checking a directory exists (not just a file):**  
Check for a file that is always present inside the directory, e.g. a report HTML or a known output file.

**Debugging a failing check:**  
Run `check-outputs` and open the CSV. The `pattern` and `actual` columns show exactly what was globbed and how many files were found. Resolve the `output_path` manually on the HPC to verify the path is correct:

```bash
ls /data/work/my_study/BIDS_derivatives/fmriprep/sub-002*.html
```
