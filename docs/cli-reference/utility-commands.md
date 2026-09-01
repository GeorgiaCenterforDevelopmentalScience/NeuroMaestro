---
title: Utility Commands
---

# Utility Commands

---

## `neuromaestro detect-subjects`

Scans a directory for subject folders matching the given prefix.

```bash
# Print detected subjects to stdout
neuromaestro detect-subjects /data/BIDS

# Save to a text file (comma-separated, one line)
neuromaestro detect-subjects /data/BIDS --output subjects.txt

# With explicit prefix (default is "sub-")
neuromaestro detect-subjects /data/raw --prefix "sub-" -o subjects.txt
```

The saved file can be passed directly to `--subjects` in `neuromaestro run`:

```bash
neuromaestro run --subjects subjects.txt ...
```

**Arguments / Options:**

| Argument/Option | Description |
|-----------------|-------------|
| `input_dir` | Directory to scan (positional, required) |
| `--output` / `-o` | Output file path — prints to stdout if omitted |
| `--prefix` / `-p` | Subject folder prefix to match (default: `sub-`) |

---

## `neuromaestro init`

Initialises a new project directory with config and script templates copied from the package defaults.

```bash
neuromaestro init /scratch/my_study
```

Creates the following layout under the given directory:

```
/scratch/my_study/
├── config/
│   ├── config.yaml
│   ├── hpc_config.yaml
│   └── project_config/
└── scripts/
    └── (template .sh scripts)
```

Pass `--config-dir /scratch/my_study/config` in all subsequent `neuromaestro` commands, or set `$NEUROMAESTRO_CONFIG_DIR` once to skip it (see [Getting Started](../getting-started/index.md#step-1-initialise-your-config-directory)).

**Arguments / Options:**

| Argument/Option | Description |
|-----------------|-------------|
| `output_dir` | Directory to initialise (positional, required) |

---

## `neuromaestro list-tasks`

Lists all task names, scripts, and dependencies from `config.yaml`.

```bash
neuromaestro list-tasks --config-dir /data/config
```

**Options:**

| Option | Description |
|--------|-------------|
| `--config-dir` | Path to config directory. Optional if `$NEUROMAESTRO_CONFIG_DIR` is set. |

---

## `neuromaestro-gui`

Launches the web dashboard.

```bash
neuromaestro-gui                 # default port 8050
neuromaestro-gui --port 8051     # if 8050 is in use
```

Open `http://localhost:8050`. The GUI has three tabs:

| Tab | Purpose |
|-----|---------|
| **Analysis Control** | Select subjects, configure pipeline, execute/dry-run, generate command preview |
| **Project Config** | Create/edit project YAML configs and results-check YAMLs |
| **Job Monitor** | Query job database, read logs, track running jobs |

---

## `neuromaestro generate-config`

Generate a blank project config template (`{project}_config.yaml`). Equivalent to clicking **Generate Template** in the GUI Project Config tab.

```bash
neuromaestro generate-config branch --config-dir /data/config

# Write to a custom directory
neuromaestro generate-config branch --config-dir /data/config \
  --output-dir /scratch/my_project/config/project_config
```

**Arguments / Options:**

| | Description |
|---|-------------|
| `PROJECT_NAME` | Project name — determines the output filename |
| `--config-dir` | Path to config directory. Optional if `$NEUROMAESTRO_CONFIG_DIR` is set. |
| `--output-dir` / `-o` | Output directory (default: `<config-dir>/project_config/`) |
| `--force` | Overwrite an existing config file |

The command refuses to overwrite an existing `{project}_config.yaml` and exits with
code 1, so regenerating a template cannot silently discard settings you have already
filled in. Pass `--force` when you really do want to start over.

The generated file is a fully-commented YAML template. Open it in the GUI editor or any text editor and fill in paths, modules, and task parameters.

---

## `neuromaestro generate-checks`

Generate a blank results-check config template (`{project}_checks.yaml`). Equivalent to clicking **New** in the GUI Results Check Config tab.

```bash
neuromaestro generate-checks branch --config-dir /data/config

# Write to a custom directory
neuromaestro generate-checks branch --config-dir /data/config \
  --output-dir /scratch/my_project/config/results_check
```

**Arguments / Options:**

| | Description |
|---|-------------|
| `PROJECT_NAME` | Project name — determines the output filename |
| `--config-dir` | Path to config directory. Optional if `$NEUROMAESTRO_CONFIG_DIR` is set. |
| `--output-dir` / `-o` | Output directory (default: `<config-dir>/results_check/`) |
| `--force` | Overwrite an existing checks file |

As with `generate-config`, an existing `{project}_checks.yaml` is never overwritten
unless `--force` is given.

The generated file contains commented examples for both `required_files` and `count_check` block types. See [Output Checks Configuration](../configuration/output-checks.md) for the full reference.
