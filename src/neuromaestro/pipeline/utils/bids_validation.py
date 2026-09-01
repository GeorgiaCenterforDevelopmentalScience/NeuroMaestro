"""BIDS validation via pybids — warning only, non-blocking."""

from pathlib import Path
from typing import Optional

import typer


def run_bids_validation(input_dir: str, work_dir: Optional[str] = None) -> None:
    from bids import BIDSLayout, BIDSLayoutIndexer

    db_path = str(Path(work_dir) / ".bids_cache.db") if work_dir else None

    typer.echo("Running BIDS validation...")
    try:
        BIDSLayout(
            input_dir,
            validate=True,
            indexer=BIDSLayoutIndexer(index_metadata=False),
            database_path=db_path,
        )
        typer.echo("BIDS validation passed.")
    except Exception as e:
        typer.echo(f"Warning: BIDS validation error: {e}")
