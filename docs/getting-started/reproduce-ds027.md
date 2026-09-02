---
title: Reproduce the Published Example
---

# Reproduce the Published Example (AOMIC-PIOP2)

Every other page in this documentation uses an invented project called `my_study`, because the paths and task names you will use are your own. This page is the exception. It walks through the one run that is fully reproducible from public data: the AOMIC-PIOP2 demonstration reported in the pipeline's methods paper.

The pipeline ships a matched config bundle for it (`ds027`), so you can run the same 13 tasks over the same 30 participants and compare against the reference outcome at the bottom of this page.

:::{note}
`ds027` is the internal project name for the run. The dataset itself is OpenNeuro accession **`ds002790`**, AOMIC-PIOP2 (Snoek et al., 2021, *Scientific Data*). It is openly downloadable with no access application.
:::

---

## What the reference run covered

| | |
|---|---|
| Participants | 30 (`sub-0001` to `sub-0030`) |
| Tasks | 13 |
| Jobs | 274 (270 per-subject array elements plus 4 group-level jobs) |
| Session label | `01` (nominal; AOMIC-PIOP2 has no session level) |

AOMIC ships as BIDS already, so the run starts at `--intermed volume`. The `unzip` and `recon` prep tasks are not exercised here. For those, see [Prep Pipeline](../pipeline-reference/prep.md).

The 13 tasks are:

| Stage | Flag | Tasks |
|-------|------|-------|
| Intermed | `--intermed volume` | `volume` |
| Resting-state | `--bids-prep rest --bids-post rest` | `rest_preprocess`, `rest_post` |
| DWI | `--bids-prep dwi --bids-post dwi` | `dwi_preprocess`, `dwi_post` |
| Task fMRI | `--staged-prep emomatching,stopsignal,workingmemory` | 3 preprocess tasks |
| Task fMRI group | `--staged-post emomatching,stopsignal,workingmemory` | 3 postprocess tasks |
| QC | `--mriqc all` | `mriqc_preprocess`, `mriqc_post` |

---

## Step 1: Download the data

The reference run used the first 30 participants by identifier, `sub-0001` to `sub-0030`. Download them into `{output}/{project}/BIDS`, which is where the pipeline expects raw BIDS data to sit and where the `recon` rule in `ds027_checks.yaml` resolves its `output_path`. Metadata first, then the subject directories:

```bash
BIDS_DIR=/path/to/ds027_out/ds027/BIDS
mkdir -p "$BIDS_DIR"

aws s3 sync --no-sign-request --region eu-west-1 \
  s3://openneuro.org/ds002790 "$BIDS_DIR" \
  --exclude "*" --include "*.tsv" --include "*.json" --exclude "derivatives/*"

for s in $(tail -n +2 "$BIDS_DIR/participants.tsv" | cut -f1 | head -30); do
  aws s3 sync --no-sign-request --region eu-west-1 \
    s3://openneuro.org/ds002790/$s "$BIDS_DIR/$s"
done
```

`$BIDS_DIR` is what you pass as `--input`, and `/path/to/ds027_out` is what you pass as `--output`. Putting the data elsewhere still runs, but the `recon` check in Step 8 then finds nothing and reports every participant as missing raw data.

---

## Step 2: Create the config directory

```bash
neuromaestro init /path/to/ds027_study
```

`neuromaestro init` copies every bundled project config and check file, so `ds027_config.yaml` and `ds027_checks.yaml` are already in place:

```
/path/to/ds027_study/
├── config/
│   ├── config.yaml
│   ├── hpc_config.yaml
│   ├── project_config/
│   │   └── ds027_config.yaml       ← the bundle you will use
│   └── results_check/
│       └── ds027_checks.yaml
└── scripts/
```

`config.yaml` already defines the `emomatching`, `stopsignal`, and `workingmemory` staged sections, so no edits are needed there.

### Paths you must change

`ds027_config.yaml` is shipped exactly as it ran on the original cluster, so its paths are site-specific. Replace each of the following with the equivalent location on your system:

| Field | Shipped value | What it needs to be |
|-------|--------------|---------------------|
| `scripts_dir` | a site path | Where you put the `ds027` scripts (Step 3) |
| `envir_dir.container_dir` | a site path | Directory holding the `.sif` containers |
| `envir_dir.virtual_envir` | a site path | The Python environment used on compute nodes |
| `envir_dir.template_dir`, `atlas_dir` | a site path | Your AFNI and atlas template directory |
| `envir_dir.freesurfer_dir` | a site path | Directory containing `license.txt` |
| `envir_dir.config_dir` | a site path | BIDS App config directory |
| `envir_dir.stimulus_dir` | a site path | Timing files generated in Step 4 |

The `global_python` and `modules` blocks use Lmod module names from the original cluster (`ml AFNI/24.3.06-foss-2023a` and similar). Substitute the module names your site actually provides. See [Project Config Guide](../configuration/project-config.md).

Container versions referenced by the bundle are fMRIPrep 25.2.5, XCP-D 0.11.0rc1, QSIPrep 1.0.0, QSIRecon 1.2.0, MRIQC 24.0.2, and AFNI 24.3.06. Different versions will run, but outputs will not match the reference exactly.

Resource profiles come from `hpc_config.yaml`, which is cluster-wide rather than per-project. Adjust partition names, time limits, and memory to your scheduler before submitting. See [HPC Config](../configuration/hpc-config.md).

---

## Step 3: Install the analysis scripts

`neuromaestro init` copies only the `template` scripts. The `ds027` scripts ship inside the installed package and need to be copied out:

```bash
python -c "import neuromaestro, pathlib; print(pathlib.Path(neuromaestro.__file__).parent / 'scripts' / 'ds027')"
```

Copy that directory to wherever you pointed `scripts_dir`. It contains 13 scripts, one per task.

---

## Step 4: Generate the AFNI timing files

The three task fMRI pipelines are AFNI based and consume `stim_times` files rather than the BIDS `events.tsv` directly. The reference run converted them with a helper script (`make_afni_timing.py`) that walks the BIDS root and writes one `.1D` per condition per subject into `stimulus_dir`.

```bash
python3 make_afni_timing.py
```

Point `envir_dir.stimulus_dir` at the output directory. The scripts expect one subdirectory per subject, named with the full BIDS ID (`sub-0001`).

:::{important}
This conversion step is dataset-specific and lives with the AOMIC materials rather than in the package. Without it, the `emomatching`, `stopsignal`, and `workingmemory` tasks have no regressors to model.
:::

---

## Step 5: Build the subject list

```bash
neuromaestro detect-subjects /path/to/ds027_out/ds027/BIDS --prefix "sub-" --output subjects.txt
```

This writes bare IDs (`0001`, `0002`, ...). The reference run used the first 30.

---

## Step 6: Dry-run

```bash
neuromaestro run \
  --subjects subjects.txt \
  --input /path/to/ds027_out/ds027/BIDS \
  --output /path/to/ds027_out \
  --work /path/to/ds027_work \
  --config-dir /path/to/ds027_study/config \
  --project ds027 --session 01 \
  --intermed volume \
  --bids-prep rest,dwi --bids-post rest,dwi \
  --staged-prep emomatching,stopsignal,workingmemory \
  --staged-post emomatching,stopsignal,workingmemory \
  --mriqc all \
  --dry-run
```

The printed DAG plan should list 13 tasks. Preflight catches missing modules, unknown profile names, and unresolvable container paths here, before anything is queued.

---

## Step 7: Submit

Drop `--dry-run` and the same command submits the run:

```bash
neuromaestro run \
  --subjects subjects.txt \
  --input /path/to/ds027_out/ds027/BIDS \
  --output /path/to/ds027_out \
  --work /path/to/ds027_work \
  --config-dir /path/to/ds027_study/config \
  --project ds027 --session 01 \
  --intermed volume \
  --bids-prep rest,dwi --bids-post rest,dwi \
  --staged-prep emomatching,stopsignal,workingmemory \
  --staged-post emomatching,stopsignal,workingmemory \
  --mriqc all
```

Nine tasks are submitted as 30-element array jobs. The three staged postprocess tasks and `mriqc_post` are group-level and submit as single jobs that wait on their upstream array.

---

## Step 8: Verify

**Merge the JSONL logs into the database.** The positional argument is the directory that contains `database/`. With the bundle's default `db_path` of `$WORK_DIR/database/pipeline_jobs.db`, that is your `--work` value **without** the project name appended:

```bash
neuromaestro merge-logs /path/to/ds027_work
```

**Check the outputs.** Here `--work` is the output data root, meaning your `--output` value **with** the project name appended. It is the directory that directly contains `BIDS/`, `AFNI_derivatives/`, `BIDS_derivatives/`, and `quality_control/`:

```bash
neuromaestro check-outputs \
  --project ds027 \
  --work /path/to/ds027_out/ds027 \
  --config-dir /path/to/ds027_study/config \
  --subjects subjects.txt \
  --session 01
```

This writes `check_results_{timestamp}.csv` into that same directory.

**Generate the report**, passing the CSV from the previous step:

```bash
neuromaestro generate-report \
  --db-path /path/to/ds027_work/database/pipeline_jobs.db \
  --project ds027 \
  --session 01 \
  --config-dir /path/to/ds027_study/config \
  --check-results /path/to/ds027_out/ds027/check_results_{timestamp}.csv
```

See [Post-Run Verification](../how-to/post-run-verification.md) for what each command reports and how to read the disagreements between them.

---

## Reference outcome

These are the numbers from the original run. They depend on tool versions and cluster behaviour, so treat them as a comparison target rather than a guarantee.

**Job outcomes:** 261 SUCCESS, 13 FAILED, 0 CANCELLED.

**Output checks:** 21 of 30 participants passed every per-subject check. The nine that did not:

| Participants | Cause |
|--------------|-------|
| `0001` | No emomatching run in the raw data |
| `0010` | No emomatching and no resting-state run in the raw data |
| `0007`, `0008`, `0014`, `0015` | fMRIPrep failure |
| `0005` | MRIQC failure |
| `0002` | Silent failure, see below |
| `0004` | False positive, see below |

Two results are worth understanding before you read your own report:

**`0002` is a silent failure.** This participant inhibited every stop trial, so the `unsuccesful_stop` condition had zero events and no timing file was written for it. AFNI's own check for missing stimulus files was disabled in the script, and the job's exit status came from the last command in the pipeline rather than from the step that failed. The database therefore recorded SUCCESS. Only `check-outputs` caught it. This is the case the paper uses to argue that job status and output verification answer different questions.

**`0004` `rest_post` is a false positive.** XCP-D succeeded, but its report HTML came in at 20 KB against a 50 KB minimum in `ds027_checks.yaml`, so the check failed on a file size threshold rather than on a real problem. HTML size thresholds are a weak signal. Completeness judgements should rest on the data files.

:::{note}
The group-level outputs from the three `_postprocess` tasks are illustrative of the coordination layer only. They are not intended as neuroscience findings, and no interpretation of them is offered here or in the paper.
:::
