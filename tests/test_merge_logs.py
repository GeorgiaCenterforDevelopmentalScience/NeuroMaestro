import pytest
import os
import json
import sqlite3
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# Add package to path
import sys
test_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(test_root / "src"))

from neuro_pipeline.pipeline.dag import DAGExecutor
from neuro_pipeline.pipeline.utils.merge_logs_create_db import merge_json_to_db, rebuild_db, merge_once


@pytest.fixture
def temp_workspace():
    """Create temporary workspace for testing"""
    tmpdir = tempfile.mkdtemp()
    workspace = {
        'root': tmpdir,
        'work_dir': os.path.join(tmpdir, 'work'),
        'input_dir': os.path.join(tmpdir, 'input'),
        'output_dir': os.path.join(tmpdir, 'output'),
        'db_path': os.path.join(tmpdir, 'work', 'log', 'pipeline_jobs.db'),
        'json_dir': os.path.join(tmpdir, 'work', 'log', 'json'),
    }
    
    # Create directories
    os.makedirs(workspace['work_dir'], exist_ok=True)
    os.makedirs(workspace['input_dir'], exist_ok=True)
    os.makedirs(workspace['output_dir'], exist_ok=True)
    os.makedirs(os.path.dirname(workspace['db_path']), exist_ok=True)
    os.makedirs(workspace['json_dir'], exist_ok=True)
    
    yield workspace
    
    # Cleanup
    shutil.rmtree(tmpdir)


@pytest.fixture
def mock_db(temp_workspace):
    """Create mock database with schema"""
    db_path = temp_workspace['db_path']
    conn = sqlite3.connect(db_path)
    
    # Create schema — must match job_db.py exactly
    conn.execute('''
        CREATE TABLE IF NOT EXISTS job_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id INTEGER,
            subject TEXT,
            task_name TEXT,
            session TEXT,
            start_time TEXT,
            end_time TEXT,
            status TEXT,
            exit_code INTEGER,
            error_msg TEXT,
            duration_hours REAL,
            log_path TEXT,
            job_id TEXT,
            node_name TEXT
        )
    ''')

    conn.execute('''
        CREATE TABLE IF NOT EXISTS command_outputs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id INTEGER,
            subject TEXT,
            task_name TEXT,
            session TEXT,
            script_name TEXT,
            command TEXT,
            stdout TEXT,
            stderr TEXT,
            exit_code INTEGER,
            execution_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            log_file_path TEXT,
            job_id TEXT
        )
    ''')
    
    conn.commit()
    conn.close()
    
    return db_path


def create_mock_json_log(json_dir, subject, task_name, job_id, status="SUCCESS"):
    """Create mock JSON log file"""
    task_dir = Path(json_dir) / task_name
    task_dir.mkdir(exist_ok=True)
    
    log_file = task_dir / f"{subject}_{task_name}_{job_id}.jsonl"
    
    # Create complete log with start and end events
    logs = [
        {
            "event": "start",
            "timestamp": datetime.now().isoformat(),
            "subject": subject,
            "task_name": task_name,
            "session": "01",
            "job_id": job_id,
            "log_path": f"/path/to/{subject}_{task_name}.log",
            "node_name": "node001"
        },
        {
            "event": "end",
            "timestamp": datetime.now().isoformat(),
            "subject": subject,
            "task_name": task_name,
            "session": "01",
            "status": status,
            "exit_code": 0 if status == "SUCCESS" else 1,
            "duration_hours": 0.5
        }
    ]
    
    # Write only end event if status is SUCCESS (complete log)
    with open(log_file, 'w') as f:
        for log in logs:
            f.write(json.dumps(log) + '\n')
    
    return str(log_file)


def create_incomplete_json_log(json_dir, subject, task_name, job_id):
    """Create incomplete JSON log (only start event)"""
    task_dir = Path(json_dir) / task_name
    task_dir.mkdir(exist_ok=True)
    
    log_file = task_dir / f"{subject}_{task_name}_{job_id}.jsonl"
    
    # Only start event (incomplete)
    log = {
        "event": "start",
        "timestamp": datetime.now().isoformat(),
        "subject": subject,
        "task_name": task_name,
        "session": "01",
        "job_id": job_id,
        "log_path": f"/path/to/{subject}_{task_name}.log",
        "node_name": "node001"
    }
    
    with open(log_file, 'w') as f:
        f.write(json.dumps(log) + '\n')
    
    return str(log_file)


class TestMergeLogsFunction:
    """Test merge_logs functionality"""
    
    def test_merge_complete_logs_only(self, temp_workspace, mock_db):
        """Test 1: merge_logs only processes complete JSON files"""
        json_dir = temp_workspace['json_dir']
        
        # Create complete and incomplete logs
        create_mock_json_log(json_dir, "sub001", "task1", "12345")
        create_incomplete_json_log(json_dir, "sub002", "task2", "12346")
        
        # Run merge
        count = merge_json_to_db(json_dir, mock_db)
        
        # Verify only complete log was merged
        assert count == 1
        
        # Check database
        conn = sqlite3.connect(mock_db)
        cursor = conn.execute("SELECT COUNT(*) FROM job_status WHERE job_id='12345'")
        assert cursor.fetchone()[0] == 1
        
        cursor = conn.execute("SELECT COUNT(*) FROM job_status WHERE job_id='12346'")
        assert cursor.fetchone()[0] == 0
        conn.close()
        
        # Verify incomplete log still exists
        incomplete_file = Path(json_dir) / "task2" / "sub002_task2_12346.jsonl"
        assert incomplete_file.exists()
    
    def test_merge_specific_job_ids(self, temp_workspace, mock_db):
        """Test 3: merge_logs only processes specified job_ids"""
        json_dir = temp_workspace['json_dir']
        
        # Create multiple complete logs
        create_mock_json_log(json_dir, "sub001", "task1", "12345")
        create_mock_json_log(json_dir, "sub002", "task1", "12346")
        create_mock_json_log(json_dir, "sub003", "task2", "12347")
        
        # Merge only specific job_ids
        target_jobs = ["12345", "12347"]
        count = merge_json_to_db(json_dir, mock_db, job_ids=target_jobs)
        
        # Should merge 2 out of 3
        assert count == 2
        
        # Verify database
        conn = sqlite3.connect(mock_db)
        cursor = conn.execute("SELECT job_id FROM job_status ORDER BY job_id")
        merged_jobs = [row[0] for row in cursor.fetchall()]
        assert set(merged_jobs) == {"12345", "12347"}
        
        # Verify non-target job still exists in JSON
        non_target_file = Path(json_dir) / "task1" / "sub002_task1_12346.jsonl"
        assert non_target_file.exists()
        conn.close()
    
    def test_merge_archives_processed_files(self, temp_workspace, mock_db):
        """Test: merge_logs archives processed files"""
        json_dir = temp_workspace['json_dir']
        
        log_file = create_mock_json_log(json_dir, "sub001", "task1", "12345")
        
        # Run merge
        count = merge_json_to_db(json_dir, mock_db)
        assert count == 1
        
        # Original file should be moved to archived/
        assert not Path(log_file).exists()
        
        archived_file = Path(json_dir) / "task1" / "archived" / Path(log_file).name
        assert archived_file.exists()


class TestDAGMergeLogsIntegration:
    """Test merge_logs integration with DAG executor"""
    
    @pytest.fixture
    def mock_config(self):
        """Mock pipeline config"""
        return {
            'tasks': {
                'utility': [
                    {
                        'name': 'merge_logs',
                        'scripts': ['merge_logs.py'],
                        'profile': 'minimal'
                    }
                ]
            }
        }
    
    @pytest.fixture
    def mock_project_config(self):
        """Mock project config"""
        return {
            'prefix': 'sub-',
            'envir_dir': {
                'container_dir': '/containers'
            }
        }
    
    def test_merge_logs_added_to_execution_order(self, mock_config):
        """Test 2: merge_logs is added after all tasks in execution order"""
        executor = DAGExecutor(mock_config)
        
        # Mock task configs
        with patch('neuro_pipeline.pipeline.utils.config_utils.find_task_config_by_name_with_project') as mock_find:
            mock_find.side_effect = lambda name, proj: {
                'name': name,
                'scripts': [f'{name}.sh'],
                'profile': 'standard'
            }
            
            # Build DAG with tasks
            requested_tasks = ['task1', 'task2', 'task3']
            execution_order = executor.build_dag(requested_tasks)
            
            # Add merge_logs (simulating execute() logic)
            merge_config = mock_config['tasks']['utility'][0]
            executor.add_task('merge_logs', merge_config)
            for task_name in execution_order:
                executor.nodes['merge_logs'].add_dependency(task_name)
            execution_order.append('merge_logs')
            
            # Verify merge_logs is last
            assert execution_order[-1] == 'merge_logs'
            
            # Verify merge_logs depends on all tasks
            merge_node = executor.nodes['merge_logs']
            assert merge_node.dependencies == {'task1', 'task2', 'task3'}
    
    def test_merge_logs_not_added_in_dry_run(self, mock_config, mock_project_config):
        """Test: merge_logs is not added during dry_run"""
        executor = DAGExecutor(mock_config)
        
        with patch('neuro_pipeline.pipeline.utils.hpc_utils.submit_slurm_job') as mock_submit:
            mock_submit.return_value = 'dry_run_job'
            
            with patch('neuro_pipeline.pipeline.utils.config_utils.find_task_config_by_name_with_project') as mock_find:
                mock_find.side_effect = lambda name, proj: {
                    'name': name,
                    'scripts': [f'{name}.sh'],
                    'profile': 'standard'
                }
                
                requested_tasks = ['task1', 'task2']
                context = {'subjects': ['sub001']}
                
                all_job_ids, _ = executor.execute(
                    requested_tasks=requested_tasks,
                    input_dir='/input',
                    output_dir='/output',
                    work_dir='/work',
                    container_dir='/containers',
                    dry_run=True,  # Dry run mode
                    context=context,
                    project_config=mock_project_config
                )
                
                # Verify merge_logs was not executed
                assert 'merge_logs' not in all_job_ids


class TestEndToEndMergeLogsWorkflow:
    """End-to-end integration test"""
    
    def test_complete_workflow(self, temp_workspace, mock_db):
        """Test complete workflow: tasks -> merge_logs -> database"""
        json_dir = temp_workspace['json_dir']
        
        # Simulate 3 tasks completing
        task_jobs = {
            'task1': ['12345', '12346'],
            'task2': ['12347'],
            'task3': ['12348', '12349']
        }
        
        # Create JSON logs for all tasks
        for task_name, job_ids in task_jobs.items():
            for i, job_id in enumerate(job_ids):
                subject = f"sub00{i+1}"
                create_mock_json_log(json_dir, subject, task_name, job_id)
        
        # Also create some unrelated logs (different job_ids)
        create_mock_json_log(json_dir, "sub999", "other_task", "99999")
        
        # Flatten all target job_ids
        all_target_jobs = []
        for jobs in task_jobs.values():
            all_target_jobs.extend(jobs)
        
        # Run merge with job_ids filter
        count = merge_json_to_db(json_dir, mock_db, job_ids=all_target_jobs)
        
        # Should merge only target jobs (5 logs)
        assert count == 5
        
        # Verify database has exactly these jobs
        conn = sqlite3.connect(mock_db)
        cursor = conn.execute("SELECT job_id FROM job_status ORDER BY job_id")
        merged_jobs = sorted([row[0] for row in cursor.fetchall()])
        assert merged_jobs == sorted(all_target_jobs)
        
        # Verify unrelated log was not merged
        cursor = conn.execute("SELECT COUNT(*) FROM job_status WHERE job_id='99999'")
        assert cursor.fetchone()[0] == 0
        
        # Verify unrelated log still exists
        unrelated_file = Path(json_dir) / "other_task" / "sub999_other_task_99999.jsonl"
        assert unrelated_file.exists()
        
        conn.close()


class TestMergeOnce:
    """Test that merge_once backs up the DB before merging"""

    def test_backup_called_when_db_exists(self, temp_workspace, mock_db):
        """merge_once calls backup_database before merging when DB already exists"""
        work_dir = temp_workspace['work_dir']
        db_path = temp_workspace['db_path']
        json_dir = temp_workspace['json_dir']
        create_mock_json_log(json_dir, "sub001", "task1", "12345")

        with patch("neuro_pipeline.pipeline.utils.db_backup.backup_database") as mock_backup:
            mock_backup.return_value = db_path + ".backup_test"
            merge_once(work_dir, db_path)

        mock_backup.assert_called_once_with(db_path, backup_dir=None)

    def test_no_backup_when_db_missing(self, temp_workspace):
        """merge_once skips backup when DB does not yet exist"""
        work_dir = temp_workspace['work_dir']
        db_path = temp_workspace['db_path']
        json_dir = temp_workspace['json_dir']
        assert not Path(db_path).exists()
        create_mock_json_log(json_dir, "sub001", "task1", "12345")

        with patch("neuro_pipeline.pipeline.utils.db_backup.backup_database") as mock_backup:
            merge_once(work_dir, db_path)

        mock_backup.assert_not_called()

    def test_backup_called_before_merge(self, temp_workspace, mock_db):
        """backup_database is called before merge_json_to_db"""
        work_dir = temp_workspace['work_dir']
        db_path = temp_workspace['db_path']
        json_dir = temp_workspace['json_dir']
        create_mock_json_log(json_dir, "sub001", "task1", "12345")

        call_order = []

        with patch("neuro_pipeline.pipeline.utils.db_backup.backup_database",
                   side_effect=lambda *a, **kw: call_order.append("backup") or db_path):
            with patch("neuro_pipeline.pipeline.utils.merge_logs_create_db.merge_json_to_db",
                       side_effect=lambda *a, **kw: call_order.append("merge") or 1):
                merge_once(work_dir, db_path)

        assert call_order == ["backup", "merge"]


class TestRebuildDb:
    """Tests for force-rebuild: rebuild a fresh db including archived JSONL files."""

    def test_rebuild_includes_archived_files(self, temp_workspace, mock_db):
        """Archived files are included in the rebuilt database."""
        json_dir = temp_workspace['json_dir']

        # Create a log, merge it (moves to archived/), then verify rebuild picks it up
        create_mock_json_log(json_dir, "sub001", "task1", "11111")
        merge_json_to_db(json_dir, mock_db)

        archived = Path(json_dir) / "task1" / "archived" / "sub001_task1_11111.jsonl"
        assert archived.exists()

        new_db_path, count = rebuild_db(temp_workspace['work_dir'], mock_db)
        assert count == 1

        conn = sqlite3.connect(new_db_path)
        row = conn.execute("SELECT job_id FROM job_status WHERE job_id='11111'").fetchone()
        conn.close()
        assert row is not None

    def test_rebuild_includes_active_and_archived(self, temp_workspace, mock_db):
        """Rebuild picks up both active (not yet merged) and archived JSONL files."""
        json_dir = temp_workspace['json_dir']

        # One archived
        create_mock_json_log(json_dir, "sub001", "task1", "11111")
        merge_json_to_db(json_dir, mock_db)

        # One still active
        create_mock_json_log(json_dir, "sub002", "task1", "22222")

        new_db_path, count = rebuild_db(temp_workspace['work_dir'], mock_db)
        assert count == 2

        conn = sqlite3.connect(new_db_path)
        jobs = {r[0] for r in conn.execute("SELECT job_id FROM job_status").fetchall()}
        conn.close()
        assert jobs == {"11111", "22222"}

    def test_rebuild_does_not_modify_original_db(self, temp_workspace, mock_db):
        """The original database is untouched after a rebuild."""
        json_dir = temp_workspace['json_dir']

        create_mock_json_log(json_dir, "sub001", "task1", "11111")
        merge_json_to_db(json_dir, mock_db)

        original_mtime = os.path.getmtime(mock_db)
        rebuild_db(temp_workspace['work_dir'], mock_db)

        assert os.path.getmtime(mock_db) == original_mtime

    def test_rebuild_creates_new_db_with_timestamp(self, temp_workspace, mock_db):
        """Rebuilt database has a timestamped name and is distinct from the original."""
        json_dir = temp_workspace['json_dir']
        create_mock_json_log(json_dir, "sub001", "task1", "11111")
        merge_json_to_db(json_dir, mock_db)

        new_db_path, _ = rebuild_db(temp_workspace['work_dir'], mock_db)

        assert os.path.exists(new_db_path)
        assert new_db_path != mock_db
        assert "pipeline_jobs_rebuild_" in os.path.basename(new_db_path)

    def test_rebuild_does_not_move_archived_files(self, temp_workspace, mock_db):
        """Files already in archived/ remain there after a rebuild."""
        json_dir = temp_workspace['json_dir']

        create_mock_json_log(json_dir, "sub001", "task1", "11111")
        merge_json_to_db(json_dir, mock_db)

        archived = Path(json_dir) / "task1" / "archived" / "sub001_task1_11111.jsonl"
        assert archived.exists()

        rebuild_db(temp_workspace['work_dir'], mock_db)

        assert archived.exists()

    def test_rebuild_raises_if_no_json_dir(self, temp_workspace, mock_db):
        """Raises FileNotFoundError when log/json/ does not exist."""
        import shutil as _shutil
        json_dir = temp_workspace['json_dir']
        _shutil.rmtree(json_dir)

        with pytest.raises(FileNotFoundError):
            rebuild_db(temp_workspace['work_dir'], mock_db)


@pytest.fixture
def full_db(temp_workspace):
    from neuro_pipeline.pipeline.utils.job_db import get_db_connection
    db_path = temp_workspace['db_path']
    conn = get_db_connection(db_path)
    conn.close()
    return db_path


def create_pipeline_log(json_dir, execution_id=1001):
    pipeline_dir = Path(json_dir) / "_pipeline"
    pipeline_dir.mkdir(exist_ok=True)
    log_file = pipeline_dir / f"execution_{execution_id}.jsonl"
    with open(log_file, 'w') as f:
        f.write(json.dumps({
            "event": "pipeline_start",
            "timestamp": "2024-01-01T09:00:00",
            "execution_id": execution_id,
            "project_name": "test_proj",
            "session": "01",
            "command_line": "neuropipe run ...",
            "input_dir": "/data/input",
            "output_dir": "/data/output",
            "work_dir": "/data/work",
            "subjects": "001,002",
            "requested_tasks": "task1",
            "dry_run": False,
            "total_jobs": 2,
            "status": "RUNNING",
        }) + '\n')
        f.write(json.dumps({
            "event": "pipeline_update",
            "total_jobs": 2,
            "status": "COMPLETED",
            "error_msg": None,
        }) + '\n')
    return str(log_file)


def create_wrapper_log(json_dir, task_name="task1", job_id="12345", execution_id=1001):
    pipeline_dir = Path(json_dir) / "_pipeline"
    pipeline_dir.mkdir(exist_ok=True)
    log_file = pipeline_dir / f"wrapper_{task_name}_99999.jsonl"
    with open(log_file, 'w') as f:
        f.write(json.dumps({
            "event": "wrapper_script",
            "timestamp": "2024-01-01T09:00:00",
            "execution_id": execution_id,
            "task_name": task_name,
            "job_id": job_id,
            "wrapper_path": f"/path/to/{task_name}_wrapper.sh",
            "full_content": "#!/bin/bash\necho test",
            "slurm_cmd": f"sbatch --partition=batch {task_name}_wrapper.sh",
            "basic_paths": "export INPUT_DIR=/data/input",
            "global_python": "",
            "env_modules": "",
            "global_env_vars": "",
            "task_params": "",
            "execute_cmd": "execute_wrapper script.sh",
        }) + '\n')
    return str(log_file)


def create_job_log_with_command_output(json_dir, subject, task_name, job_id):
    task_dir = Path(json_dir) / task_name
    task_dir.mkdir(exist_ok=True)
    log_file = task_dir / f"{subject}_{task_name}_{job_id}.jsonl"
    with open(log_file, 'w') as f:
        for record in [
            {"event": "start", "timestamp": datetime.now().isoformat(),
             "subject": subject, "task_name": task_name, "session": "01",
             "job_id": job_id, "log_path": f"/path/{subject}.log", "node_name": "node001"},
            {"event": "command_output", "subject": subject, "task_name": task_name,
             "session": "01", "script_name": f"{task_name}.sh", "command": "bash script.sh",
             "stdout": "output here", "stderr": "", "exit_code": 0,
             "log_file_path": f"/path/{subject}.log", "job_id": job_id},
            {"event": "end", "timestamp": datetime.now().isoformat(),
             "subject": subject, "task_name": task_name, "session": "01",
             "status": "SUCCESS", "exit_code": 0, "duration_hours": 0.5},
        ]:
            f.write(json.dumps(record) + '\n')
    return str(log_file)


class TestMergePipelineLogs:

    def test_pipeline_log_inserted_into_db(self, temp_workspace, full_db):
        json_dir = temp_workspace['json_dir']
        create_pipeline_log(json_dir, execution_id=1001)
        merge_json_to_db(json_dir, full_db)
        conn = sqlite3.connect(full_db)
        row = conn.execute(
            "SELECT execution_id FROM pipeline_executions WHERE execution_id=1001"
        ).fetchone()
        conn.close()
        assert row is not None

    def test_pipeline_log_archived_after_merge(self, temp_workspace, full_db):
        json_dir = temp_workspace['json_dir']
        log_file = create_pipeline_log(json_dir, execution_id=1002)
        merge_json_to_db(json_dir, full_db)
        assert not Path(log_file).exists()
        archived = Path(json_dir) / "_pipeline" / "archived" / Path(log_file).name
        assert archived.exists()

    def test_pipeline_log_not_inserted_without_pipeline_start(self, temp_workspace, full_db):
        json_dir = temp_workspace['json_dir']
        pipeline_dir = Path(json_dir) / "_pipeline"
        pipeline_dir.mkdir(exist_ok=True)
        bad_file = pipeline_dir / "execution_9999.jsonl"
        bad_file.write_text(json.dumps({"event": "other_event"}) + '\n')
        merge_json_to_db(json_dir, full_db)
        conn = sqlite3.connect(full_db)
        row = conn.execute(
            "SELECT execution_id FROM pipeline_executions WHERE execution_id=9999"
        ).fetchone()
        conn.close()
        assert row is None

    def test_pipeline_update_sets_status(self, temp_workspace, full_db):
        json_dir = temp_workspace['json_dir']
        create_pipeline_log(json_dir, execution_id=1003)
        merge_json_to_db(json_dir, full_db)
        conn = sqlite3.connect(full_db)
        row = conn.execute(
            "SELECT status FROM pipeline_executions WHERE execution_id=1003"
        ).fetchone()
        conn.close()
        assert row[0] == "COMPLETED"


class TestMergeWrapperLogs:

    def test_wrapper_log_inserted_into_db(self, temp_workspace, full_db):
        json_dir = temp_workspace['json_dir']
        create_wrapper_log(json_dir, task_name="task1", job_id="55555")
        merge_json_to_db(json_dir, full_db)
        conn = sqlite3.connect(full_db)
        row = conn.execute(
            "SELECT task_name FROM wrapper_scripts WHERE job_id='55555'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "task1"

    def test_wrapper_log_archived_after_merge(self, temp_workspace, full_db):
        json_dir = temp_workspace['json_dir']
        log_file = create_wrapper_log(json_dir, task_name="task1", job_id="55556")
        merge_json_to_db(json_dir, full_db)
        assert not Path(log_file).exists()
        archived = Path(json_dir) / "_pipeline" / "archived" / Path(log_file).name
        assert archived.exists()

    def test_non_wrapper_event_jsonl_skipped(self, temp_workspace, full_db):
        json_dir = temp_workspace['json_dir']
        pipeline_dir = Path(json_dir) / "_pipeline"
        pipeline_dir.mkdir(exist_ok=True)
        bad_file = pipeline_dir / "wrapper_bad_99.jsonl"
        bad_file.write_text(json.dumps({"event": "something_else"}) + '\n')
        merge_json_to_db(json_dir, full_db)
        conn = sqlite3.connect(full_db)
        count = conn.execute("SELECT COUNT(*) FROM wrapper_scripts").fetchone()[0]
        conn.close()
        assert count == 0


class TestCommandOutputMerge:

    def test_command_output_inserted_when_event_present(self, temp_workspace, mock_db):
        json_dir = temp_workspace['json_dir']
        create_job_log_with_command_output(json_dir, "sub001", "task1", "77777")
        merge_json_to_db(json_dir, mock_db)
        conn = sqlite3.connect(mock_db)
        row = conn.execute(
            "SELECT stdout FROM command_outputs WHERE job_id='77777'"
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "output here"

    def test_no_command_output_row_when_event_absent(self, temp_workspace, mock_db):
        json_dir = temp_workspace['json_dir']
        create_mock_json_log(json_dir, "sub001", "task1", "88888")
        merge_json_to_db(json_dir, mock_db)
        conn = sqlite3.connect(mock_db)
        count = conn.execute(
            "SELECT COUNT(*) FROM command_outputs WHERE job_id='88888'"
        ).fetchone()[0]
        conn.close()
        assert count == 0


class TestMergeBadJson:

    def test_bad_jsonl_does_not_crash_merge(self, temp_workspace, mock_db):
        json_dir = temp_workspace['json_dir']
        bad_dir = Path(json_dir) / "task_bad"
        bad_dir.mkdir()
        (bad_dir / "bad_file.jsonl").write_text("this is not valid json\n")
        count = merge_json_to_db(json_dir, mock_db)
        assert count == 0

    def test_valid_files_still_merged_after_bad_file(self, temp_workspace, mock_db):
        json_dir = temp_workspace['json_dir']
        bad_dir = Path(json_dir) / "task_x"
        bad_dir.mkdir()
        (bad_dir / "bad_file.jsonl").write_text("not json\n")
        create_mock_json_log(json_dir, "sub001", "task_y", "66666")
        count = merge_json_to_db(json_dir, mock_db)
        assert count == 1


class TestMergeOnceEdgeCases:

    def test_no_json_dir_returns_without_error(self, temp_workspace, mock_db, capsys):
        work_dir = temp_workspace['work_dir']
        db_path = temp_workspace['db_path']
        # the fixture pre-creates json_dir, so this branch is only reachable once
        # it is removed
        shutil.rmtree(temp_workspace['json_dir'])

        merge_once(work_dir, db_path)

        # returns ahead of the backup step, so nothing is written
        assert "No JSON logs" in capsys.readouterr().out
        assert not list(Path(db_path).parent.glob("*.backup_*.db"))

    def test_backup_failure_does_not_abort_merge(self, temp_workspace, mock_db):
        work_dir = temp_workspace['work_dir']
        db_path = temp_workspace['db_path']
        json_dir = temp_workspace['json_dir']
        create_mock_json_log(json_dir, "sub001", "task1", "12345")

        with patch("neuro_pipeline.pipeline.utils.db_backup.backup_database",
                   side_effect=RuntimeError("disk full")):
            merge_once(work_dir, db_path)

        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM job_status").fetchone()[0]
        conn.close()
        assert count == 1


class TestJobStatusRowTargeting:
    """The end event used to be applied with
    WHERE subject=? AND task_name=? AND session=? AND status='RUNNING',
    which can touch rows from earlier runs. It now targets lastrowid.
    """

    def test_rerun_of_same_subject_task_session_creates_two_rows(self, temp_workspace, mock_db):
        json_dir = temp_workspace['json_dir']
        create_mock_json_log(json_dir, "sub001", "task1", "12345", status="FAILED")
        merge_json_to_db(json_dir, mock_db)
        create_mock_json_log(json_dir, "sub001", "task1", "12346", status="SUCCESS")
        merge_json_to_db(json_dir, mock_db)

        conn = sqlite3.connect(mock_db)
        rows = conn.execute(
            "SELECT job_id, status FROM job_status "
            "WHERE subject='sub001' AND task_name='task1' ORDER BY id"
        ).fetchall()
        conn.close()
        assert rows == [("12345", "FAILED"), ("12346", "SUCCESS")]

    def test_rerun_does_not_overwrite_earlier_run_status(self, temp_workspace, mock_db):
        json_dir = temp_workspace['json_dir']
        create_mock_json_log(json_dir, "sub001", "task1", "12345", status="FAILED")
        merge_json_to_db(json_dir, mock_db)
        create_mock_json_log(json_dir, "sub001", "task1", "12346", status="SUCCESS")
        merge_json_to_db(json_dir, mock_db)

        conn = sqlite3.connect(mock_db)
        failed = conn.execute(
            "SELECT COUNT(*) FROM job_status WHERE job_id='12345' AND status='FAILED'"
        ).fetchone()[0]
        conn.close()
        assert failed == 1

    def test_no_row_left_in_running_state(self, temp_workspace, mock_db):
        json_dir = temp_workspace['json_dir']
        create_mock_json_log(json_dir, "sub001", "task1", "12345")
        create_mock_json_log(json_dir, "sub002", "task1", "12346")
        merge_json_to_db(json_dir, mock_db)

        conn = sqlite3.connect(mock_db)
        running = conn.execute(
            "SELECT COUNT(*) FROM job_status WHERE status='RUNNING'"
        ).fetchone()[0]
        conn.close()
        assert running == 0

    def test_failed_update_rolls_back_the_insert(self, temp_workspace, mock_db):
        """A mid-file failure must not leave an uncommitted INSERT that the
        next file's commit() would sweep in.

        sqlite3.Connection.execute is read-only, so the failure is injected
        through a proxy rather than patch.object.
        """
        json_dir = temp_workspace['json_dir']
        create_mock_json_log(json_dir, "sub001", "task1", "12345")

        from neuro_pipeline.pipeline.utils import merge_logs_create_db as mod

        class FlakyConn:
            def __init__(self, conn, fail_prefix):
                self._conn = conn
                self._fail_prefix = fail_prefix
                self.failures = 0
                self.rolled_back = False

            def execute(self, sql, *args):
                if sql.strip().upper().startswith(self._fail_prefix):
                    self.failures += 1
                    raise sqlite3.OperationalError("boom")
                return self._conn.execute(sql, *args)

            def commit(self):
                return self._conn.commit()

            def rollback(self):
                self.rolled_back = True
                return self._conn.rollback()

        conn = sqlite3.connect(mock_db)
        flaky = FlakyConn(conn, "UPDATE JOB_STATUS")
        mod._merge_jobs(Path(json_dir) / "task1", flaky, archive=False)

        assert flaky.failures == 1
        assert flaky.rolled_back
        leftover = conn.execute(
            "SELECT COUNT(*) FROM job_status WHERE job_id='12345'"
        ).fetchone()[0]
        conn.close()
        assert leftover == 0

    def test_file_not_archived_when_merge_fails(self, temp_workspace, mock_db):
        json_dir = temp_workspace['json_dir']
        log_file = create_mock_json_log(json_dir, "sub001", "task1", "12345")

        from neuro_pipeline.pipeline.utils import merge_logs_create_db as mod

        class FailingConn:
            def __init__(self, conn):
                self._conn = conn

            def execute(self, sql, *args):
                if sql.strip().upper().startswith("UPDATE JOB_STATUS"):
                    raise sqlite3.OperationalError("boom")
                return self._conn.execute(sql, *args)

            def commit(self):
                return self._conn.commit()

            def rollback(self):
                return self._conn.rollback()

        conn = sqlite3.connect(mock_db)
        count = mod._merge_jobs(Path(json_dir) / "task1", FailingConn(conn), archive=True)
        conn.close()

        assert count == 0
        assert Path(log_file).exists()


def create_job_log_without_job_id(json_dir, subject, task_name):
    """A start event written before the wrapper could resolve a SLURM id."""
    task_dir = Path(json_dir) / task_name
    task_dir.mkdir(exist_ok=True)
    log_file = task_dir / f"{subject}_{task_name}_nojobid.jsonl"
    with open(log_file, 'w') as f:
        for record in [
            {"event": "start", "timestamp": datetime.now().isoformat(),
             "subject": subject, "task_name": task_name, "session": "01",
             "job_id": None, "log_path": f"/path/{subject}.log", "node_name": "node001"},
            {"event": "end", "timestamp": datetime.now().isoformat(),
             "subject": subject, "task_name": task_name, "session": "01",
             "status": "SUCCESS", "exit_code": 0, "duration_hours": 0.5},
        ]:
            f.write(json.dumps(record) + '\n')
    return str(log_file)


class TestJobIdFilter:
    """job_id.startswith(...) raised AttributeError on a null id, and the broad
    except reported it as if the file were unreadable.
    """

    def test_null_job_id_is_skipped_without_an_error(self, temp_workspace, mock_db, capsys):
        json_dir = temp_workspace['json_dir']
        create_job_log_without_job_id(json_dir, "sub001", "task1")
        merge_json_to_db(json_dir, mock_db, job_ids=["12345"])
        assert "Error:" not in capsys.readouterr().out

    def test_null_job_id_matches_no_filter(self, temp_workspace, mock_db):
        json_dir = temp_workspace['json_dir']
        create_job_log_without_job_id(json_dir, "sub001", "task1")
        merge_json_to_db(json_dir, mock_db, job_ids=["12345"])

        conn = sqlite3.connect(mock_db)
        count = conn.execute("SELECT COUNT(*) FROM job_status").fetchone()[0]
        conn.close()
        assert count == 0

    def test_matching_log_still_merges_alongside_it(self, temp_workspace, mock_db):
        json_dir = temp_workspace['json_dir']
        create_job_log_without_job_id(json_dir, "sub001", "task1")
        create_mock_json_log(json_dir, "sub002", "task1", "12345")
        merge_json_to_db(json_dir, mock_db, job_ids=["12345"])

        conn = sqlite3.connect(mock_db)
        subjects = [r[0] for r in conn.execute("SELECT subject FROM job_status")]
        conn.close()
        assert subjects == ["sub002"]

    def test_null_job_id_merges_when_no_filter_is_given(self, temp_workspace, mock_db):
        json_dir = temp_workspace['json_dir']
        create_job_log_without_job_id(json_dir, "sub001", "task1")
        merge_json_to_db(json_dir, mock_db)

        conn = sqlite3.connect(mock_db)
        count = conn.execute("SELECT COUNT(*) FROM job_status").fetchone()[0]
        conn.close()
        assert count == 1


class TestPipelineScanIsScopedToExecutionLogs:
    """_pipeline/ holds both execution_*.jsonl and the much larger
    wrapper_*.jsonl; _merge_pipeline used to open and parse both.
    """

    def test_wrapper_logs_are_not_touched_by_the_pipeline_pass(self, temp_workspace, full_db):
        from neuro_pipeline.pipeline.utils import merge_logs_create_db as mod
        json_dir = temp_workspace['json_dir']
        wrapper_log = create_wrapper_log(json_dir)

        conn = sqlite3.connect(full_db)
        count = mod._merge_pipeline(Path(json_dir) / "_pipeline", conn, archive=True)
        conn.close()

        assert count == 0
        assert Path(wrapper_log).exists()

    def test_a_corrupt_wrapper_log_is_reported_once_not_twice(self, temp_workspace, full_db, capsys):
        json_dir = temp_workspace['json_dir']
        pipeline_dir = Path(json_dir) / "_pipeline"
        pipeline_dir.mkdir(exist_ok=True)
        (pipeline_dir / "wrapper_task1_99999.jsonl").write_text("{not json\n")

        merge_json_to_db(json_dir, full_db)

        assert capsys.readouterr().out.count("wrapper_task1_99999.jsonl") == 1

    def test_execution_logs_still_merge_after_scoping(self, temp_workspace, full_db):
        json_dir = temp_workspace['json_dir']
        create_pipeline_log(json_dir, execution_id=2001)
        create_wrapper_log(json_dir)
        merge_json_to_db(json_dir, full_db)

        conn = sqlite3.connect(full_db)
        executions = conn.execute(
            "SELECT COUNT(*) FROM pipeline_executions WHERE execution_id=2001"
        ).fetchone()[0]
        wrappers = conn.execute("SELECT COUNT(*) FROM wrapper_scripts").fetchone()[0]
        conn.close()
        assert executions == 1
        assert wrappers == 1


class TestArchiveFailureIsVisible:
    """A merged log that cannot be moved aside gets merged again next run, and
    the message used to be indistinguishable from a parse error.
    """

    def _merge_with_broken_move(self, json_dir, db_path):
        from neuro_pipeline.pipeline.utils import merge_logs_create_db as mod
        with patch.object(mod.shutil, "move", side_effect=OSError("read-only")):
            return merge_json_to_db(json_dir, db_path)

    def test_message_points_at_force_rebuild(self, temp_workspace, mock_db, capsys):
        json_dir = temp_workspace['json_dir']
        create_mock_json_log(json_dir, "sub001", "task1", "12345")
        self._merge_with_broken_move(json_dir, mock_db)

        out = capsys.readouterr().out
        assert "could not archive" in out
        assert "force-rebuild" in out

    def test_rows_are_still_committed(self, temp_workspace, mock_db):
        json_dir = temp_workspace['json_dir']
        create_mock_json_log(json_dir, "sub001", "task1", "12345")
        self._merge_with_broken_move(json_dir, mock_db)

        conn = sqlite3.connect(mock_db)
        rows = conn.execute("SELECT COUNT(*) FROM job_status").fetchone()[0]
        conn.close()
        assert rows == 1

    def test_merged_count_is_not_under_reported(self, temp_workspace, mock_db):
        json_dir = temp_workspace['json_dir']
        create_mock_json_log(json_dir, "sub001", "task1", "12345")
        assert self._merge_with_broken_move(json_dir, mock_db) == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v', '-s'])
