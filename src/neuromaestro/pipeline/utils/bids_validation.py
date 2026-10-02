"""BIDS validation with bids-validator-deno. Warning only, never blocks a run."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import typer

VALIDATOR = "bids-validator-deno"
TIMEOUT_SECONDS = 600
MAX_LOCATIONS = 3


def _find_validator():
    # pip puts the console script next to the interpreter, which need not be on PATH
    search = os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")])
    return shutil.which(VALIDATOR, path=search)


def _where(issue):
    if issue.get("location"):
        return issue["location"]
    affects = issue.get("affects") or []
    return ", ".join(affects) if isinstance(affects, list) else str(affects)


def _report(issues):
    errors = [i for i in issues if i.get("severity") == "error"]
    warnings = Counter(i.get("code") for i in issues if i.get("severity") == "warning")
    n_warnings = sum(warnings.values())
    if not errors:
        typer.echo(f"BIDS validation passed ({n_warnings} warning(s)).")
        return

    typer.echo(f"BIDS validation: {len(errors)} error(s), {n_warnings} warning(s)")
    places_by_code = {}
    for issue in errors:
        places_by_code.setdefault(str(issue.get("code")), []).append(_where(issue))
    for code, places in sorted(places_by_code.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        distinct = list(dict.fromkeys(p for p in places if p))
        shown = ", ".join(distinct[:MAX_LOCATIONS]) + (", ..." if len(distinct) > MAX_LOCATIONS else "")
        typer.echo(f"  ERROR {code} ({len(places)}): {shown}")
    if warnings:
        typer.echo("  warnings: " + ", ".join(f"{code} {n}" for code, n in warnings.most_common()))


def run_bids_validation(input_dir: str) -> None:
    exe = _find_validator()
    if exe is None:
        typer.echo(f"Warning: {VALIDATOR} not found, BIDS validation skipped.")
        return

    typer.echo("Running BIDS validation...")
    # deno keeps its caches in SQLite WAL files, which do not work on an NFS home directory
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as deno_dir:
        env = {**os.environ, "DENO_DIR": deno_dir, "DENO_NO_UPDATE_CHECK": "1"}
        try:
            result = subprocess.run(
                [exe, "--json", input_dir],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=TIMEOUT_SECONDS,
                env=env,
            )
        except subprocess.TimeoutExpired:
            typer.echo(f"Warning: BIDS validation timed out after {TIMEOUT_SECONDS} s, skipped.")
            return
        except OSError as e:
            typer.echo(f"Warning: BIDS validation could not start: {e}")
            return

    try:
        issues = json.loads(result.stdout)["issues"]["issues"]
    except (ValueError, KeyError, TypeError):
        typer.echo(f"Warning: BIDS validation gave no result (exit code {result.returncode}), skipped.")
        if "CagedHeap" in result.stderr:
            typer.echo("  The validator could not reserve virtual memory. "
                       "A ulimit -v below about 33 GB prevents it from starting.")
        else:
            first = next((line.strip() for line in result.stderr.splitlines() if line.strip()), "")
            if first:
                typer.echo(f"  {first}")
        return

    _report(issues)
