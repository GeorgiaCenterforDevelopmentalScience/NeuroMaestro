---
title: CLI Reference
---

# CLI Reference

## Commands

| Command | Description |
|---------|-------------|
| `neuromaestro run` | Submit pipeline jobs to SLURM |
| `neuromaestro init` | Initialise a new project directory with config and script templates |
| `neuromaestro check-outputs` | Inspect which subjects completed a task |
| `neuromaestro detect-subjects` | Find subject IDs in a directory |
| `neuromaestro list-tasks` | List all configured tasks |
| `neuromaestro generate-config` | Generate a blank project config template |
| `neuromaestro generate-checks` | Generate a blank results-check config template |
| `neuromaestro merge-logs` | Manually merge JSONL logs into the SQLite database |
| `neuromaestro force-rebuild` | Rebuild a fresh database from all JSONL logs, including archived |
| `neuromaestro generate-report` | Generate a standalone HTML report from the job database |
| `neuromaestro-gui` | Launch the web-based GUI |

---

::::{grid} 2
:::{card} neuromaestro run
:link: run
All flags for submitting pipeline jobs — subjects, stages, dry-run, resume, wait.
:::
:::{card} Database Commands
:link: database-commands
`check-outputs`, `merge-logs`, `force-rebuild`, `generate-report`, and the database schema.
:::
:::{card} Utility Commands
:link: utility-commands
`detect-subjects`, `list-tasks`, `neuromaestro-gui`, `generate-config`, `generate-checks`.
:::
::::
