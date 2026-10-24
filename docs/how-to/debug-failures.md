---
title: Debug & Troubleshoot
---

# Debug & Troubleshoot

:::{tip} Recommended diagnosis order
1. **Read the log file** — the per-subject execution log almost always contains the specific error message. Start here before anything else.
2. **Inspect the wrapper script** — verify environment variables and paths. If the error is unclear, add `echo` statements to the processing script to print the actual input/output paths at runtime. Most failures are caused by a misconfigured path or a subject ID format mismatch.
3. **Investigate the module environment** — only if the paths look correct and the error points to a missing command or library.
:::

---

## Step 1: Identify Which Subjects Failed

Run [Post-Run Verification](post-run-verification.md) first. Use `check-outputs` to see which subjects are missing expected output files, and the job database for exit codes and error messages. Once you know which subjects and tasks need attention, come back here to diagnose why.

---

## Step 2: Read the SLURM Logs

SLURM output and error files are in `{work_dir}/log/{task_name}/`, where `{work_dir}` is the `run` `--work` with the project name appended (e.g. `/data/work/my_study`):

```
# Array jobs
{work_dir}/log/{task_name}/{task_name}_{job_id}-{array_task_id}.out
{work_dir}/log/{task_name}/{task_name}_{job_id}-{array_task_id}.err

# Non-array jobs
{work_dir}/log/{task_name}/{task_name}_{job_id}.out
{work_dir}/log/{task_name}/{task_name}_{job_id}.err
```

The detailed per-subject execution log (stdout + stderr combined) is written by the wrapper:

```
# Array jobs
{work_dir}/log/{task_name}/sub-{subject}/{task_name}_{job_id}_{array_task_id}_{timestamp}.log

# Non-array jobs
{work_dir}/log/{task_name}/{task_name}_{job_id}_{timestamp}.log
```

---

## Step 3: Inspect the Wrapper Script

The generated wrapper script shows exactly what ran on the compute node:

```bash
cat /data/work/my_study/log/wrapper/afni_cards_preprocessing_*.sh
```

Verify:
- Module load commands look correct
- Environment variables (`$TEMPLATE_DIR`, `$CONTAINER_DIR`, etc.) are set
- Script path exists

---

## Step 4: Test the Module Environment

SSH to a compute node (or use `srun`) and manually load the modules:

```bash
srun --pty bash
ml AFNI/24.3.06-foss-2023a
afni_proc.py --help     # should print help if loaded correctly
```

---

## Step 5: Check Script Line Endings

Windows line endings cause `$'\r': command not found` errors:

```bash
# Run inside the scripts_dir set in your project config
file afni_cards_preprocessing.sh
# Should say "POSIX shell script" or "Bourne-Again shell script", NOT "CRLF"

# Fix if needed:
dos2unix *.sh
```

---

## Database Shows Incomplete Records?

If the database is missing jobs (e.g., after a cluster crash), merge the raw JSONL logs manually. Pass the `run` `--work` directory, without the project name:

```bash
neuromaestro merge-logs /data/work
```

JSONL event logs in the `json/` directory next to the database (`/data/work/database/json/` by default) accumulate independently of the SQLite database. Merging re-processes any unarchived files and fills in gaps.

If the JSONL files were already archived by a previous merge and the database is still incomplete (e.g., after restoring from backup), use `force-rebuild` to create a fresh database from all logs including archived ones:

```bash
neuromaestro force-rebuild /data/work
# → writes pipeline_jobs_rebuild_{timestamp}.db next to the original
```

---

## Quick Diagnosis Checklist

- [ ] Is the config file named `{project}_config.yaml` and in the right directory?
- [ ] Does `module avail` show the modules in your config?
- [ ] Are all paths in `envir_dir` absolute and correct on the HPC?
- [ ] Does the container `.sif` file exist in `container_dir`?
- [ ] Does the `license.txt` exist in `freesurfer_dir`?
- [ ] Are shell scripts using Unix line endings?
- [ ] Does the Python venv on the compute nodes contain `typer`?

---

## Error Reference

### Setup & Configuration

**"No subjects found"**
- Check that `prefix` in your project config (`prefix: "sub-"`) matches your directory naming
- Verify `--input` points to the correct directory
- Run `neuromaestro detect-subjects /data/BIDS` to preview what the pipeline sees

**"Config not found: .../{project}_config.yaml"**
- The config file must be named exactly `{project}_config.yaml`
- It must be in `<config-dir>/project_config/`
- Check: `ls <config-dir>/project_config/`

**"Task not found" / task name mismatch**
- Task names are case-sensitive — `cards_preprocess` ≠ `Cards_Preprocess`
- The name must match exactly between `config.yaml` and your project config `tasks` section
- Run `neuromaestro list-tasks` to see all registered task names

**GUI won't start**
- Check if port 8050 is already in use: `lsof -i :8050`
- Try a different port: `neuromaestro-gui --port 8051`
- Verify the package is installed: `pip show neuromaestro`

### SLURM & Job Submission

**`module: command not found` in job logs**
- The module system is not initialized in the batch environment
- Add to the top of `global_python` in your project config:
  ```yaml
  global_python:
    - source /etc/profile.d/modules.sh
    - ml Python/3.11.3-GCCcore-12.3.0
    - . /home/$USER/venv/bin/activate
  ```

**`SLURM Job ID: N/A` in the per-subject log**
- The wrapper ran without a SLURM job ID, so it was not started as a SLURM job (for example it was run directly with `bash`)
- Check: `which sbatch` (must be available)
- Check account: `sacctmgr show user $USER`

**Jobs are queued but never start**
- Check resource limits: `sacctmgr show assoc user=$USER`
- Reduce concurrent array jobs: lower `array_limit` on the task's resource profile in `hpc_config.yaml`

### Container Mounting (Apptainer / Singularity)

**`FATAL: container creation failed: ... squashfuse_ll failed to mount ... in 10s`**

Apptainer mounts a `.sif` image with squashfuse (a userspace FUSE mount) and gives up if the mount is not ready within a hard 10 second limit. The image lives on the shared network filesystem (`container_dir`, e.g. `/work`). When many jobs mount the same large image at the same time (a job array releasing a batch at once), they all read the image over the network and contend for storage bandwidth, so individual mounts exceed 10s and fail.

This is probabilistic, not deterministic. It is far more likely with:
- Large images (fMRIPrep, QSIPrep, QSIRecon, MRIQC are 10 to 20 GB)
- High concurrency (many array tasks starting in the same window)
- Peak cluster hours (Monday morning, weekday daytime) and shared (non-dedicated) nodes

The bundled `ds027` example scripts avoid this by staging the image to node-local disk before running. The template scripts that `neuromaestro init` copies do not include this block, so add it to your own container scripts if you see the timeout. The block works as follows:
- The image is copied once to `/tmp/${USER}_sif/` on the compute node, and the container runs from that local copy. A local squashfuse mount completes in well under a second, so the 10s timeout never triggers.
- A per-node `flock` guarantees only one job on a node copies the image; other jobs wait and then reuse the same copy, so a burst of same-node jobs does not each copy in parallel.
- If staging fails (see disk-full below), the script prints a warning and falls back to the network image, so the job still runs.
- `APPTAINER_TMPDIR` / `SINGULARITY_TMPDIR` are also pointed at node-local disk for session scratch.

This is the block near the top of each `ds027` container script (before `singularity run`). Copy it into any container script, then run `singularity run ... ${local_container} ...` instead of `${CONTAINER_DIR}/${CONTAINER}`:

```bash
# Point Apptainer session/cache to node-local disk to avoid squashfuse mount timeout
apptainer_tmp="${SLURM_TMPDIR:-${TMPDIR:-/tmp}}/apptainer_${SLURM_JOB_ID:-$$}"
mkdir -p "${apptainer_tmp}"
export APPTAINER_TMPDIR="${apptainer_tmp}"
export APPTAINER_CACHEDIR="${apptainer_tmp}"
export SINGULARITY_TMPDIR="${apptainer_tmp}"
export SINGULARITY_CACHEDIR="${apptainer_tmp}"

# Stage container image to node-local disk to avoid squashfuse mount timeout.
# Per-node lock: only one job copies, others wait then reuse. Fall back to the
# network image if staging fails (e.g. local disk full).
src_container="${CONTAINER_DIR}/${CONTAINER}"
node_cache="/tmp/${USER}_sif"
staged="${node_cache}/${CONTAINER}"
local_container="${src_container}"
mkdir -p "${node_cache}" 2>/dev/null
(
    flock 9
    if [ ! -s "${staged}" ] || [ "$(stat -c%s "${staged}" 2>/dev/null)" != "$(stat -c%s "${src_container}")" ]; then
        tmp_copy="${staged}.tmp.$$"
        cp "${src_container}" "${tmp_copy}" 2>/dev/null && mv -f "${tmp_copy}" "${staged}" || rm -f "${tmp_copy}"
    fi
) 9>"${node_cache}/${CONTAINER}.lock"
if [ -s "${staged}" ] && [ "$(stat -c%s "${staged}" 2>/dev/null)" = "$(stat -c%s "${src_container}")" ]; then
    local_container="${staged}"
else
    echo "WARNING: staging to ${node_cache} failed (disk full?), using network image"
fi
```

If mount timeouts still appear (staging fell back to the network image), also:
- Lower concurrency via `array_limit` on the task's resource profile in `hpc_config.yaml`
- Submit off-peak, or use dedicated nodes when available

**`cp: ... No space left on device` when staging the image**

Node-local `/tmp` filled up. On shared nodes `/tmp` is shared with other users' jobs, so it can be nearly full before your copy starts. Scripts with the staging block handle this gracefully (fall back to the network image), so the job does not hard-fail, but that job loses the staging benefit.
- Inspect a compute node: `srun --pty bash -c 'df -h -T /tmp; du -sh /tmp/${USER}_sif'`
- Clear your own leftovers on a node: `srun -w <node> bash -c 'rm -rf /tmp/${USER}_sif'`
- Most clusters reap `/tmp` automatically (epilog or tmpwatch); only your own files (`/tmp/${USER}_sif`, `/tmp/apptainer_*`) are yours to remove

### Python Environment

**`ModuleNotFoundError: No module named 'typer'`**
- The Python environment on the compute node is missing required packages
- Ensure your venv/conda env includes `typer`, which the wrapper's job logger imports. Everything else it uses is in the Python standard library
- Test on a compute node:
  ```bash
  srun --pty bash -c "source /path/to/venv/bin/activate && python -c 'import typer'"
  ```

### Resume & Output Checks

**`--resume` does not skip any subjects**
- Check that `{project}_checks.yaml` exists in `<config-dir>/results_check/`
- Tasks with no entry in the checks file are always submitted in full (warning is printed)
- `--resume` does not filter subjects during `--dry-run`, so a dry-run always lists every subject
- `--resume` resolves `{work_dir}` in the checks file to `--output` with the project name appended. Run `check-outputs` with that path as `--work` to see what `--resume` sees

**`check-outputs` reports unexpected failures**
- Open the CSV at `{--work}/check_results_{timestamp}.csv`. The `pattern` column shows the check's pattern as written in the checks file (relative to `output_path`, placeholders not filled in), and `actual` shows how many files matched
- Verify `output_path` resolves correctly for your subjects by checking the path manually on the HPC
- Check `expected_count` and `tolerance` match your actual data
