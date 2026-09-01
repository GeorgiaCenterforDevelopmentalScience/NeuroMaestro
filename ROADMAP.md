# Project Roadmap – NeuroMaestro

This document outlines the planned development path for NeuroMaestro.  
It is intended to guide future contributions and provide clarity for collaborators and users.  

Version numbers follow semantic versioning; "x" denotes future patch-level releases within the minor version series.

---

## Vision
A robust, modular, reproducible pipeline for neuroimaging preprocessing and analysis, following BIDS standards and enabling flexible workflows across modalities (structural, functional, rs-fMRI).

---

# Completed Features

## v0.14.x
- **Handbook:** Complete documentation site with CLI reference, configuration guides, pipeline task reference, and internals. Automated deployment via GitHub Actions.
- **Multi-session support:** `check-outputs` and `generate-report` now accept multiple session IDs.
- **Test expansion:** Added test modules for core, db backup, job database, and report generator; integration-level testing completed in production.
- **Script updates:** Container versions updated; postprocessing and group analysis scripts added.
- **Frontend:** Interface improvements completed.

## v0.13.x
- **CLI redesign:** Replaced hard-coded modality flags with abstract `--bids-prep` / `--staged-prep` flags driven by `config.yaml`. Adding a new modality no longer requires backend changes.
- **Dynamic DAG visualization:** Pipeline graph is generated dynamically from the DAG definition.
- **HTML summary report:** Self-contained run summary generated after each pipeline execution.
- Resume functionality with per-task output checking before re-submission.
- PBS scheduler support alongside existing Slurm backend.
- `hpc_config.yaml` and `config.yaml` refactored to centralize resource profiles and pipeline definitions.
- BIDS validation (non-blocking, warning-only).
- Test coverage expanded: interface, PBS backend, input resolution, task name validation.

## v0.12.x
- Enhanced task parameter usage in CLI: Simplified `--task-prep` options (e.g., `--task-prep cards`) with task-specific configurations.
- Configurable script directories per project for flexible script management.

# Milestones

_No active milestones. Future work will be defined as needed._
