#!/usr/bin/env python3
"""Convert BIDS events.tsv files into AFNI married stim_times files, one .1D per condition."""

import csv
from pathlib import Path

# Edit before running. OUT_DIR must match envir_dir.stimulus_dir in the project config.
ROOT = Path("/path/to/ds027_out/ds027/BIDS")
OUT_DIR = Path("/path/to/time_stimulus")

# Block duration in seconds, or None for one event per trial.
TASKS = {"stopsignal": None, "workingmemory": None, "emomatching": 30.0}

NA = {"n/a", "na", "nan", "", "none"}


def is_na(value):
    return value is None or value.strip().lower() in NA


def read_trials(path):
    trials = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            if is_na(row["onset"]):
                continue
            duration = 0.0 if is_na(row.get("duration")) else float(row["duration"])
            trials.append((row["trial_type"], float(row["onset"]), duration))
    return trials


def collapse_blocks(trials, block_duration):
    blocks = []
    for trial_type, onset, _ in trials:
        if not blocks or blocks[-1][0] != trial_type:
            blocks.append((trial_type, onset, block_duration))
    return blocks


def write_timing(trials, outdir, prefix):
    # Onsets are relative to the first saved volume, so no offset is applied.
    by_condition = {}
    for trial_type, onset, duration in trials:
        # Group trials by condition, each as an AFNI married "onset:duration" token.
        by_condition.setdefault(trial_type, []).append(f"{onset:.4f}:{duration:.4f}")
    outdir.mkdir(parents=True, exist_ok=True)
    for condition, tokens in by_condition.items():
        with open(outdir / f"{prefix}_{condition}.1D", "w") as fh:
            fh.write(" ".join(tokens) + "\n")
    return len(by_condition)


def main():
    missing = []
    for subdir in sorted(d for d in ROOT.glob("sub-*") if d.is_dir()):
        sub = subdir.name
        for task, block_duration in TASKS.items():
            path = subdir / "func" / f"{sub}_task-{task}_acq-seq_events.tsv"
            if not path.exists():
                missing.append(f"{sub} {task}")
                continue
            trials = read_trials(path)
            if block_duration:
                trials = collapse_blocks(trials, block_duration)
            n = write_timing(trials, OUT_DIR / sub, f"{sub}_{task}")
            print(f"{sub} {task}: {n} condition files")
    for item in missing:
        print(f"no events file: {item}")


if __name__ == "__main__":
    main()
