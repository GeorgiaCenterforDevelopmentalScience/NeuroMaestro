# Dev Log - [Neuroimage-Pipeline]

---
## [0.16.0-alpha] – 2026-07-28

### Added
- Report section **Reported SUCCESS but Output Check Failed**: lists jobs the database recorded as successful whose output checks failed, so silent failures no longer require eyeballing two matrices.
- `generate-report --config-dir`: lists report tasks in pipeline order instead of alphabetically.
- `merge-logs` now reports how many logs it skipped because the job was killed before it could write an end event.
- `generate-config` and `generate-checks` take `--force`; without it they refuse to overwrite an existing file instead of silently replacing your settings.
- The GUI wrapper inspector shows which project and session a wrapper came from.

### Changed
- `check-outputs --session` is now required. Its value is recorded in every result row, which is what keeps a failure attributable to a session. Projects without sessions may pass any value. The GUI enforces the same rule.
- Output checks moved to a shared function used by both the CLI and the GUI, so the two cannot drift apart.
- A config key that maps to a reserved shell variable (`PATH`, `LD_LIBRARY_PATH`, and similar) is now rejected instead of silently overwriting it in the job environment.

### Removed
- Leftover machinery for the `merge_logs` task, which has not been defined in `config.yaml` since the task-name refactor, plus a few unused parameters and helpers. The `merge-logs` command itself is unaffected.
- `database.include_project_name` from the generated project config template. It was never read by any code.

### Fixed
- Report tasks were always listed alphabetically; the task order was read before any config was loaded.
- `check-outputs` without `--session` checked all sessions at once, so a file found in one session was reported as a pass for every session.
- Subject IDs lost their leading zeros when the check-results CSV was read back (`001` became `1`).
- A task name missing from `config.yaml` was silently skipped, and later surfaced as a misleading "Circular dependency detected".
- Job logging failures in the wrapper were never reported, because the warning checked the exit code of `tee` rather than of the logging command.
- `merge-logs` could overwrite job records from earlier runs, and left partial rows behind when a log file failed to merge.
- `generate-config` wrote `db_path` under `log/` while everything else expects `database/`, so `merge-logs` could not find a newly generated project's database.
- Array jobs ran with an empty subject when the array range was wider than the subject list.
- Submitting more than about 65 subjects at once could abort with a path-length error on Python below 3.13.
- Config values containing `$` or backticks were expanded or executed on the compute node instead of being passed through as written.
- The array job pattern was cached on first use, so switching config directory in the GUI kept applying the previous project's setting.
- Every session in a report showed the same wrapper script, so a session processed with an older container was documented with a newer one. Wrappers are now scoped to their own project and session.
- A failed run lost the original traceback, which pointed at the re-raise rather than at where it broke.

### Tests
- Added regression tests for all of the above, including the first tests that run `wrapper_functions.sh` under bash.

### Docs
- Documented the `--session` requirement, the new report section, and why a `SUCCESS` status alone does not confirm an analysis succeeded.
- Corrected where the database actually lives: `$WORK_DIR` in `database.db_path` expands to `--work` without the project name, so projects sharing a `--work` share one database while their job logs stay separate.

---
## [0.15.0-alpha] – 2026-07-21

### Added
- Config and processing scripts for the AOMIC dataset (Snoek et al., 2021).
- Group-level postprocessing scripts (t-test, LMER).
- Optional GPU support via a `gres` key in HPC resource profiles.

### Changed
- Improved container handling: local caching and refactored staging to avoid squashfuse mount timeouts.
- GUI input fields now persist across sessions.

---
## [0.14.2-alpha] – 2026-05-02

### Added
- `NEUROPIPE_CONFIG_DIR` environment variable: all commands that previously required `--config-dir` now fall back to this variable, making it optional. Set it once in `~/.bashrc` to avoid passing `--config-dir` on every command. Explicit `--config-dir` always takes precedence.
- `neuropipe init` now prints a tip with the exact `export` line to add to `~/.bashrc`.

### Changed
- `neuropipe init` no longer generates project config files. Copy `template_config.yaml` as a starting point instead.
- Report generation and GUI job monitor further enhanced for multi-session data; related functions and tests refactored for clarity.

### Docs
- Updated Getting Started, CLI Reference (run, utility commands), and README to document the new env var.

---
## [0.14.1-alpha] – 2026-04-29

### Tests
- Added test files for core, db backup, job database, and report generator.
- Expanded `test_dag.py` and `test_hpc_utils.py` coverage.

### Changed
- `check-outputs` and `generate-report` now support multiple session IDs.
- Updated container versions for qsiprep, qsirecon, and fmriprep; standardized session ID parameters across preprocessing scripts.
- Added postprocessing scripts for new modalities.

### Docs
- Updated CLI reference for `check-outputs` and `generate-report` to document multi-session usage.
- Added GitHub Actions workflow for automated handbook deployment.

---
## [0.14.0-alpha] – 2026-04-13

### Added
- **Handbook (initial release):** First complete version of the project documentation site, covering CLI reference, configuration guides, pipeline task reference, how-to guides, and internals.

---
## [0.13.2-alpha] – 2026-04-13

### Changed
- Database backup now runs on `neuropipe merge-logs` instead of `neuropipe run`. Each merge creates a snapshot of the database before new records are written; the last 10 backups are kept.
- `execution_id` added to database and logging: `job_status`, `command_outputs`, and `wrapper_scripts` tables now link back to the originating `pipeline_executions` row via `execution_id`.
- Refactored subject parsing and detection; job monitor callbacks now support auto-detection of subjects and wildcard session matching in `check-outputs`.
- Updated query output format for execution details in `job_db.py`.

### Tests
- Added tests for backup behavior in `merge_once`.
- Aligned `mock_db` schema with production schema; added wildcard session matching tests for `check-outputs`.

---
## [0.13.1-alpha] – 2026-04-10

### Added
- **Force rebuild:** Database and UI now support a force-rebuild option to regenerate outputs regardless of existing state.
- **Results-check template generator:** New `neuropipe generate-checks` CLI command scaffolds a blank results-check config template.

### Changed
- Renamed task `recon_bids` → `recon` across pipeline for consistency.
- Replaced `structural` terminology with `intermed` throughout pipeline configuration and code.
- Centralized config directory references in `output_checker.py` and `preflight.py`.
- Refactored job monitor layout for improved usability.
- Refactored HTML summary report generation.
- Refactored config callbacks.

### Fixed
- Downloaded DAG visualization image was too small; corrected sizing.
- Config file could not be saved from the interface due to a callback bug.

### Other
- Added clientside callback for DAG visualization download.
- Added skip BIDS validation toggle and download DAG visualization button to interface.

---

## [0.13.0-alpha] – 2026-04-04

### Changed
- **CLI redesign (breaking):** Replaced hard-coded modality flags (`--rest-prep`, `--dwi-prep`) with two abstract flags:
  - `--bids-prep <modalities>` — for standard BIDS pipelines (e.g. fMRIPrep) that go directly from reconstruction to preprocessing.
  - `--staged-prep <modalities>` — for local staged pipelines (e.g. AFNI, FSL) that require intermediate steps (e.g. sswarper) before modality preprocessing.
  - Modalities are now declared in `config.yaml`; no backend changes are needed when adding new modalities.
- **Config refactor:** Both `config.yaml` and `hpc_config.yaml` were restructured to support the new pipeline model and to centralize HPC resource profiles and defaults.

### Added
- **Dynamic DAG visualization:** Pipeline graph is now generated and rendered dynamically from the DAG definition, replacing the previous static plot.
- **HTML summary report:** A self-contained HTML report is generated at the end of each run summarizing task outcomes, logs, and pipeline structure.
- **Resume functionality:** Tasks can now be resumed from the last successful checkpoint; each task's expected outputs are checked before re-submission.
- PBS scheduler support: HPC backend now supports both Slurm and PBS/Torque job submission.
- BIDS validation: Optional pre-run BIDS validation via pybids (warning-only, non-blocking).

### Fixed
- Fixed database configuration issue in the interface that prevented saving project settings.

### Other
- Interface: Project configuration page enhanced; callback functions reorganized.
- Tests: Added unit tests for interface, input directory resolution, PBS backend smoke tests, and task name validation.

## [0.12.2-alpha] – 2026-03-10
### Added
- Enhanced task parameter usage: CLI commands now support flexiable `--task-prep` options (e.g., `--task-prep cards`) after configuration in config files, with support for task-specific configurations like `task_afni`.
- Configurable script directories: Each project can now specify its own `script_dir` path for greater flexibility in script management.

## [0.12.1-alpha] – 2026-01-21
### Removed
- Deprecated DB function completely.

## [0.12.0-alpha] – 2025-12-15

### Added
- Automatic database file backup:
  - Each run now creates a backup.
  - Keeps a maximum of 10 backups; older backups are automatically removed.
- Default DAG job (`merge_logs`) added to automatically merge all JSON logs into a single database file after all tasks complete (archived JSONL files are excluded).  
- Standalone scripts for:
  - Manual backup of database files.
  - Manual merging of JSON logs into a database file, for flexible user use.  

### Changed
- Refactored database handling:
  - Replaced the previous DB file format with JSONL-based storage for safer, more reliable logging.  
  - Integrated new logging and merging mechanism into DAG execution flow.  

### Fixed
- Resolved critical issue where canceling jobs (e.g., via `scancel`) could corrupt the database file.  
- Improved robustness of database operations under incomplete or interrupted runs.  

### Removed
- Deprecated DB handling code prone to corruption during job interruptions.

## [0.11.1-alpha] – 2025-12-12
### Changed
- Updated `config_dir` in project config yaml.

### Fixed
- Fixed an issue where IDs could not be detected when the prefix was empty.

### Removed
- Remove WAL mode configuration from database connection setup.
- Removed hard-coded `config_dir` in dcm2bids script.

## [0.11.0-alpha] – 2025-12-10
### Changed
- Interface layout and logic were refactored for better clarity and maintainability.
- CLI command interface was revised, improving workflow handling for RS and task analyses.
- Database model and path resolution logic were improved for greater consistency.

### Added
- Database visualization page was introduced.

### Fixed
- Configuration file generation in the interface module was corrected.

### Removed
- NIfTI file viewer functionality was removed from the interface.
- `fieldmap` and `afni_surface` CLI were removed.

---

## [0.10.0-alpha] – 2025-07-06
### Added
- New CLI arguments: `session`, `prefix`, `project`.
- Automatic BIDS ID extraction.
- Project-level configuration YAML generator.
- Command history logging module.
- Job status logging system with SQL backend.
- DAG builder module and workflow plot generation.
- Environment test suite for analysis scripts.

### Changed
- Simplified resting-state pipeline; removed legacy AFNI volume-based `rest_prep`.
- Cleaned and reorganized argument structure.
- Improved debug logging (directory/file echo).
- Updated template handling, TR removal, and smoothing workflow.

### Fixed
- Enhanced workflow/error summary logging.

### Removed
- Deprecated AFNI volume-based resting-state preprocessing arguments.

---

## [0.1.0-dev] – 2025-07-01
### Added
- Initial project structure and module layout.
- Drafted CLI argument parsing and usage documentation.
- Basic DAG module structure.
- Script cleanup and inline comments.

### Changed
- Minor internal refactoring and project organization improvements.

---
