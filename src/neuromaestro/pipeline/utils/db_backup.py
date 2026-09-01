import typer
import shutil
from pathlib import Path
from datetime import datetime

app = typer.Typer(help="Database backup and recovery utility")

@app.command("backup")
def backup_database(
    db_path: str = typer.Argument(..., help="Database file path"),
    backup_dir: str = typer.Option(None, help="Backup directory (default: db_path/backup)")
):
    """Backup database file"""
    db_file = Path(db_path)
    
    if not db_file.exists():
        typer.echo(f"Database not found: {db_path}", err=True)
        raise typer.Exit(1)
    
    # Default backup directory
    if backup_dir is None:
        backup_dir = db_file.parent / "backup"
    else:
        backup_dir = Path(backup_dir)
    
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    # Create backup filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{db_file.stem}.backup_{timestamp}{db_file.suffix}"
    backup_path = backup_dir / backup_name
    
    # Copy database
    shutil.copy2(db_file, backup_path)
    typer.echo(f"Backup created: {backup_path}")
    
    # Cleanup old backups (keep last 10)
    cleanup_old_backups(backup_dir, db_file.stem, keep=10)
    
    return str(backup_path)

@app.command("restore")
def restore_database(
    backup_path: str = typer.Argument(..., help="Backup file path or 'latest'"),
    db_path: str = typer.Argument(..., help="Target database path"),
    backup_dir: str = typer.Option(None, help="Backup directory (if using 'latest')")
):
    """Restore database from backup"""
    
    # Handle 'latest' keyword
    if backup_path.lower() == "latest":
        if backup_dir is None:
            backup_dir = Path(db_path).parent / "backup"
        else:
            backup_dir = Path(backup_dir)
        
        if not backup_dir.exists():
            typer.echo(f"Backup directory not found: {backup_dir}", err=True)
            raise typer.Exit(1)
        
        # Find latest backup
        db_stem = Path(db_path).stem
        backups = sorted(backup_dir.glob(f"{db_stem}.backup_*"), reverse=True)
        
        if not backups:
            typer.echo(f"No backups found in: {backup_dir}", err=True)
            raise typer.Exit(1)
        
        backup_path = str(backups[0])
        typer.echo(f"Using latest backup: {backup_path}")
    
    backup_file = Path(backup_path)
    if not backup_file.exists():
        typer.echo(f"Backup not found: {backup_path}", err=True)
        raise typer.Exit(1)
    
    db_file = Path(db_path)
    
    # Backup current database before restore
    if db_file.exists():
        temp_backup = db_file.parent / f"{db_file.stem}.before_restore{db_file.suffix}"
        shutil.copy2(db_file, temp_backup)
        typer.echo(f"Current database backed up to: {temp_backup}")
    
    # Restore
    shutil.copy2(backup_file, db_file)
    typer.echo(f"Database restored from: {backup_path}")

def cleanup_old_backups(backup_dir: Path, db_stem: str, keep: int = 10):
    """Keep only the latest N backups"""
    backups = sorted(backup_dir.glob(f"{db_stem}.backup_*"), reverse=True)
    
    if len(backups) > keep:
        for old_backup in backups[keep:]:
            old_backup.unlink()
            typer.echo(f"Removed old backup: {old_backup.name}")

if __name__ == "__main__":
    app()