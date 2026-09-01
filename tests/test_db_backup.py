"""
test_db_backup.py

Tests for pipeline/utils/db_backup.py:
  - cleanup_old_backups: keeps last N, deletes older
  - backup_database CLI: creates timestamped file; default and custom dirs; missing db
  - restore_database CLI: restores from path; 'latest' keyword; pre-restore backup;
    missing backup dir / no backups / missing file
"""

import pytest
from pathlib import Path
from typer.testing import CliRunner

from neuromaestro.pipeline.utils.db_backup import app, cleanup_old_backups

runner = CliRunner()


def _make_db(path: Path, content: str = "db_content") -> Path:
    path.write_text(content)
    return path


def _make_backups(backup_dir: Path, stem: str, count: int) -> list[Path]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for i in range(count):
        f = backup_dir / f"{stem}.backup_2024010{i % 10}_12000{i}.db"
        f.write_text(f"backup {i}")
        files.append(f)
    return files


# ---------------------------------------------------------------------------
# cleanup_old_backups
# ---------------------------------------------------------------------------

class TestCleanupOldBackups:

    def test_no_deletion_when_under_limit(self, tmp_path):
        _make_backups(tmp_path, "pipeline_jobs", count=8)
        cleanup_old_backups(tmp_path, "pipeline_jobs", keep=10)
        remaining = list(tmp_path.glob("pipeline_jobs.backup_*.db"))
        assert len(remaining) == 8

    def test_no_deletion_when_exactly_at_limit(self, tmp_path):
        _make_backups(tmp_path, "pipeline_jobs", count=10)
        cleanup_old_backups(tmp_path, "pipeline_jobs", keep=10)
        remaining = list(tmp_path.glob("pipeline_jobs.backup_*.db"))
        assert len(remaining) == 10

    def test_deletes_oldest_when_over_limit(self, tmp_path):
        files = _make_backups(tmp_path, "pipeline_jobs", count=12)
        cleanup_old_backups(tmp_path, "pipeline_jobs", keep=10)
        remaining = list(tmp_path.glob("pipeline_jobs.backup_*.db"))
        assert len(remaining) == 10

    def test_keeps_most_recent_files(self, tmp_path):
        files = _make_backups(tmp_path, "pipeline_jobs", count=12)
        # sorted descending by name → files[-2] and files[-1] are the two oldest
        expected_deleted = sorted(files)[: 2]
        cleanup_old_backups(tmp_path, "pipeline_jobs", keep=10)
        for f in expected_deleted:
            assert not f.exists()

    def test_does_not_touch_other_stems(self, tmp_path):
        _make_backups(tmp_path, "pipeline_jobs", count=12)
        other = tmp_path / "other_db.backup_20240101_120000.db"
        other.write_text("other")
        cleanup_old_backups(tmp_path, "pipeline_jobs", keep=10)
        assert other.exists()


# ---------------------------------------------------------------------------
# backup_database
# ---------------------------------------------------------------------------

class TestBackupDatabase:

    def test_creates_backup_in_default_dir(self, tmp_path):
        db = _make_db(tmp_path / "pipeline_jobs.db")
        result = runner.invoke(app, ["backup", str(db)])
        assert result.exit_code == 0
        backups = list((tmp_path / "backup").glob("pipeline_jobs.backup_*.db"))
        assert len(backups) == 1

    def test_backup_content_matches_original(self, tmp_path):
        db = _make_db(tmp_path / "pipeline_jobs.db", content="original_data")
        runner.invoke(app, ["backup", str(db)])
        backup_file = list((tmp_path / "backup").glob("*.db"))[0]
        assert backup_file.read_text() == "original_data"

    def test_creates_backup_in_custom_dir(self, tmp_path):
        db = _make_db(tmp_path / "pipeline_jobs.db")
        custom = tmp_path / "my_backups"
        result = runner.invoke(app, ["backup", str(db), "--backup-dir", str(custom)])
        assert result.exit_code == 0
        backups = list(custom.glob("pipeline_jobs.backup_*.db"))
        assert len(backups) == 1

    def test_backup_filename_contains_stem(self, tmp_path):
        db = _make_db(tmp_path / "pipeline_jobs.db")
        runner.invoke(app, ["backup", str(db)])
        backup_file = list((tmp_path / "backup").glob("*.db"))[0]
        assert backup_file.name.startswith("pipeline_jobs.backup_")

    def test_exits_when_db_not_found(self, tmp_path):
        result = runner.invoke(app, ["backup", str(tmp_path / "nonexistent.db")])
        assert result.exit_code == 1

    def test_old_backups_pruned_after_eleven(self, tmp_path):
        db = _make_db(tmp_path / "pipeline_jobs.db")
        backup_dir = tmp_path / "backup"
        _make_backups(backup_dir, "pipeline_jobs", count=10)
        runner.invoke(app, ["backup", str(db)])
        remaining = list(backup_dir.glob("pipeline_jobs.backup_*.db"))
        assert len(remaining) == 10


# ---------------------------------------------------------------------------
# restore_database
# ---------------------------------------------------------------------------

class TestRestoreDatabase:

    def test_restores_from_explicit_path(self, tmp_path):
        backup = tmp_path / "pipeline_jobs.backup_20240101_120000.db"
        backup.write_text("backup_data")
        db = _make_db(tmp_path / "pipeline_jobs.db", content="old_data")
        result = runner.invoke(app, ["restore", str(backup), str(db)])
        assert result.exit_code == 0
        assert db.read_text() == "backup_data"

    def test_creates_pre_restore_backup_of_current_db(self, tmp_path):
        backup = tmp_path / "pipeline_jobs.backup_20240101_120000.db"
        backup.write_text("backup_data")
        db = _make_db(tmp_path / "pipeline_jobs.db", content="current_data")
        runner.invoke(app, ["restore", str(backup), str(db)])
        pre_restore = tmp_path / "pipeline_jobs.before_restore.db"
        assert pre_restore.exists()
        assert pre_restore.read_text() == "current_data"

    def test_latest_keyword_selects_newest_backup(self, tmp_path):
        db = tmp_path / "pipeline_jobs.db"
        backup_dir = tmp_path / "backup"
        backups = _make_backups(backup_dir, "pipeline_jobs", count=3)
        newest = sorted(backups)[-1]
        newest.write_text("newest_backup")
        result = runner.invoke(app, ["restore", "latest", str(db),
                                     "--backup-dir", str(backup_dir)])
        assert result.exit_code == 0
        assert db.read_text() == "newest_backup"

    def test_latest_exits_when_backup_dir_missing(self, tmp_path):
        db = tmp_path / "pipeline_jobs.db"
        result = runner.invoke(app, ["restore", "latest", str(db),
                                     "--backup-dir", str(tmp_path / "nonexistent")])
        assert result.exit_code == 1

    def test_latest_exits_when_no_backups_exist(self, tmp_path):
        db = tmp_path / "pipeline_jobs.db"
        backup_dir = tmp_path / "backup"
        backup_dir.mkdir()
        result = runner.invoke(app, ["restore", "latest", str(db),
                                     "--backup-dir", str(backup_dir)])
        assert result.exit_code == 1

    def test_exits_when_explicit_backup_missing(self, tmp_path):
        db = tmp_path / "pipeline_jobs.db"
        result = runner.invoke(app, ["restore",
                                     str(tmp_path / "nonexistent.db"), str(db)])
        assert result.exit_code == 1

    def test_restore_works_when_db_does_not_exist_yet(self, tmp_path):
        backup = tmp_path / "pipeline_jobs.backup_20240101_120000.db"
        backup.write_text("backup_data")
        db = tmp_path / "new_db.db"
        result = runner.invoke(app, ["restore", str(backup), str(db)])
        assert result.exit_code == 0
        assert db.read_text() == "backup_data"
