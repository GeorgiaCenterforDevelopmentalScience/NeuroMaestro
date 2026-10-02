"""
test_resume.py

Tests for DAGExecutor.execute() resume mode (dag.py):
  - completed subjects are skipped per task
  - all-complete task is skipped entirely
  - task with no checks config still runs normally
  - DAG dependency order preserved under resume
    (rest_post waits for rest_preprocess even when recon is skipped)
"""

import pytest
from unittest.mock import patch, MagicMock

from tests.conftest import MOCK_CONFIG, MOCK_PROJECT_CONFIG

CONFIG_PATH = "neuromaestro.pipeline.utils.config_utils.config"


def make_executor():
    with patch(CONFIG_PATH, MOCK_CONFIG):
        from neuromaestro.pipeline.dag import DAGExecutor
        ex = DAGExecutor(MOCK_CONFIG)
        ex.project_config = MOCK_PROJECT_CONFIG
        return ex


class TestDAGExecutorResume:
    """
    Tests for resume behaviour inside DAGExecutor.execute().
    _execute_single_task is mocked so no real sbatch calls are made.
    OutputChecker is mocked to control which subjects appear "completed".
    """

    SUBJECTS = ["001", "002", "003"]

    def _run_execute(self, requested_tasks, completed_map,
                     checks_config_path="fake_checks.yaml",
                     group_tasks=(), group_passes=True, group_rows=None):
        executor = make_executor()

        mock_execute = MagicMock(side_effect=lambda node, **kwargs: [f"job_{node.name}"])

        def fake_pending(task_name, subjects):
            done = set(completed_map.get(task_name, []))
            return [s for s in subjects if s not in done]

        mock_checker = MagicMock()
        mock_checker.get_pending_subjects.side_effect = fake_pending
        # Must be set explicitly: a bare MagicMock returns a truthy mock, which
        # would route every per-subject task down the group branch.
        mock_checker.is_group.side_effect = lambda task_name: task_name in group_tasks
        mock_checker.check_group.side_effect = lambda task_name: (
            group_rows if group_rows is not None
            else [{"status": "PASS" if group_passes else "FAIL"}]
        )
        mock_checker.warn_missing_configs.return_value = []

        with patch(CONFIG_PATH, MOCK_CONFIG), \
             patch.object(executor, "_execute_single_task", mock_execute), \
             patch(
                 "neuromaestro.pipeline.dag.OutputChecker",
                 return_value=mock_checker,
             ):
            all_job_ids, _ = executor.execute(
                requested_tasks=requested_tasks,
                input_dir="/input",
                output_dir="/output",
                work_dir="/work",
                container_dir="/containers",
                dry_run=False,
                context={"subjects": self.SUBJECTS},
                option_env={"session": "01"},
                project_config=MOCK_PROJECT_CONFIG,
                resume=True,
                checks_config_path=checks_config_path,
            )

        return executor, all_job_ids, mock_execute, mock_checker

    def test_no_resume_submits_all_subjects(self):
        """Without --resume every task is submitted with the full subject list."""
        executor = make_executor()
        mock_execute = MagicMock(return_value=["job_1"])

        with patch(CONFIG_PATH, MOCK_CONFIG), \
             patch.object(executor, "_execute_single_task", mock_execute):
            executor.execute(
                requested_tasks=["rest_preprocess"],
                input_dir="/in", output_dir="/out", work_dir="/work",
                container_dir="/c", dry_run=False,
                context={"subjects": self.SUBJECTS},
                option_env={"session": "01"},
                project_config=MOCK_PROJECT_CONFIG,
                resume=False,
            )

        _, kwargs = mock_execute.call_args
        submitted = kwargs["subjects"].split(",")
        assert set(submitted) == set(self.SUBJECTS)

    def test_resume_skips_completed_subjects(self):
        """Completed subjects are removed from the submitted subject list."""
        _, all_job_ids, mock_execute, _ = self._run_execute(
            requested_tasks=["rest_preprocess"],
            completed_map={"rest_preprocess": ["001"]},
        )

        _, kwargs = mock_execute.call_args
        submitted = set(kwargs["subjects"].split(","))
        assert "001" not in submitted
        assert {"002", "003"}.issubset(submitted)

    def test_resume_skips_task_entirely_when_all_complete(self, capsys):
        """If all subjects are done for a task, _execute_single_task is never called for it."""
        _, all_job_ids, mock_execute, _ = self._run_execute(
            requested_tasks=["rest_preprocess"],
            completed_map={"rest_preprocess": self.SUBJECTS},
        )

        assert all_job_ids["rest_preprocess"] == []
        mock_execute.assert_not_called()
        assert "[resume] rest_preprocess: all subjects complete, skipping task." in capsys.readouterr().out.splitlines()

    def test_resume_partially_complete_task_still_submits(self):
        """At least one pending subject → job is still submitted."""
        _, all_job_ids, mock_execute, _ = self._run_execute(
            requested_tasks=["rest_preprocess"],
            completed_map={"rest_preprocess": ["001", "002"]},
        )

        mock_execute.assert_called_once()
        assert all_job_ids["rest_preprocess"] != []

    def test_resume_respects_dag_dependency_order(self):
        """
        Scenario: recon complete, preprocess + post_fc pending.
        post_fc must still receive wait_jobs from preprocess job id.
        """
        _, all_job_ids, mock_execute, _ = self._run_execute(
            requested_tasks=["recon", "rest_preprocess", "rest_post"],
            completed_map={"recon": self.SUBJECTS},
        )

        assert all_job_ids["recon"] == []
        assert all_job_ids["rest_preprocess"] != []

        calls = mock_execute.call_args_list
        post_fc_call = next(
            (c for c in calls if c[0][0].name == "rest_post"), None
        )
        assert post_fc_call is not None
        wait_jobs = post_fc_call[1]["wait_jobs"]
        assert any("rest_preprocess" in j for j in wait_jobs)

    def test_resume_with_nothing_completed_submits_every_subject(self):
        """get_pending_subjects returning the full list must not filter anything.

        This is also what an unconfigured task looks like from here: the real
        OutputChecker returns no completed subjects for a task absent from the
        checks YAML (see test_output_checker.TestPendingCompleted).
        """
        _, all_job_ids, mock_execute, mock_checker = self._run_execute(
            requested_tasks=["rest_preprocess"],
            completed_map={},
        )

        mock_execute.assert_called_once()
        _, kwargs = mock_execute.call_args
        submitted = set(kwargs["subjects"].split(","))
        assert submitted == set(self.SUBJECTS)
        mock_checker.get_pending_subjects.assert_called_once()

    def test_resume_skips_group_task_when_group_result_passes(self, capsys):
        """A group-scope task with a passing group result is skipped whole."""
        _, all_job_ids, mock_execute, _ = self._run_execute(
            requested_tasks=["rest_preprocess"],
            completed_map={},
            group_tasks={"rest_preprocess"},
            group_passes=True,
        )

        assert all_job_ids["rest_preprocess"] == []
        mock_execute.assert_not_called()
        assert "[resume] rest_preprocess: group result complete, skipping task." in capsys.readouterr().out.splitlines()

    def test_resume_group_task_resubmits_all_subjects_when_group_fails(self):
        """A failing group result resubmits the task with the full subject list."""
        _, _, mock_execute, mock_checker = self._run_execute(
            requested_tasks=["rest_preprocess"],
            completed_map={"rest_preprocess": ["001"]},
            group_tasks={"rest_preprocess"},
            group_passes=False,
        )

        mock_execute.assert_called_once()
        _, kwargs = mock_execute.call_args
        assert set(kwargs["subjects"].split(",")) == set(self.SUBJECTS)
        # Group tasks are all-or-nothing, so per-subject filtering must not run.
        mock_checker.get_pending_subjects.assert_not_called()

    def test_resume_group_task_with_any_failing_row_is_resubmitted(self):
        """One failing row among passing ones still resubmits the whole group."""
        _, _, mock_execute, _ = self._run_execute(
            requested_tasks=["rest_preprocess"],
            completed_map={},
            group_tasks={"rest_preprocess"},
            group_rows=[{"status": "PASS"}, {"status": "FAIL"}],
        )

        mock_execute.assert_called_once()
        _, kwargs = mock_execute.call_args
        assert set(kwargs["subjects"].split(",")) == set(self.SUBJECTS)

    def test_resume_group_task_without_check_rows_is_resubmitted(self):
        """No check rows is not evidence of completion, so the group still runs."""
        _, _, mock_execute, _ = self._run_execute(
            requested_tasks=["rest_preprocess"],
            completed_map={},
            group_tasks={"rest_preprocess"},
            group_rows=[],
        )

        mock_execute.assert_called_once()

    def test_resume_false_does_not_instantiate_checker(self):
        """When resume=False, OutputChecker should never be imported/instantiated."""
        executor = make_executor()
        mock_execute = MagicMock(return_value=["job_1"])

        with patch(CONFIG_PATH, MOCK_CONFIG), \
             patch.object(executor, "_execute_single_task", mock_execute), \
             patch("neuromaestro.pipeline.dag.OutputChecker") as mock_cls:
            executor.execute(
                requested_tasks=["rest_preprocess"],
                input_dir="/in", output_dir="/out", work_dir="/work",
                container_dir="/c", dry_run=False,
                context={"subjects": self.SUBJECTS},
                option_env={"session": "01"},
                project_config=MOCK_PROJECT_CONFIG,
                resume=False,
            )

        mock_cls.assert_not_called()

    def test_dry_run_skips_resume_filtering(self):
        """dry_run=True + resume=True: resume filtering is bypassed."""
        executor = make_executor()
        mock_execute = MagicMock(return_value=["dry_run_job"])
        mock_checker = MagicMock()
        mock_checker.warn_missing_configs.return_value = []
        mock_checker.is_group.return_value = False

        with patch(CONFIG_PATH, MOCK_CONFIG), \
             patch.object(executor, "_execute_single_task", mock_execute), \
             patch("neuromaestro.pipeline.dag.OutputChecker", return_value=mock_checker):
            executor.execute(
                requested_tasks=["rest_preprocess"],
                input_dir="/in", output_dir="/out", work_dir="/work",
                container_dir="/c", dry_run=True,
                context={"subjects": self.SUBJECTS},
                option_env={"session": "01"},
                project_config=MOCK_PROJECT_CONFIG,
                resume=True,
                checks_config_path="fake.yaml",
            )

        mock_checker.get_pending_subjects.assert_not_called()
        mock_checker.check_group.assert_not_called()
        mock_execute.assert_called_once()
        _, kwargs = mock_execute.call_args
        assert set(kwargs["subjects"].split(",")) == set(self.SUBJECTS)


class TestResumeChecksTheOutputTree:
    """The checks YAML resolves {work_dir} against the tree output_pattern writes
    to, which is output_dir. Building the checker from work_dir made every glob
    miss whenever the two differ, and resume then silently re-ran everything.
    """

    def _execute_with(self, **overrides):
        executor = make_executor()
        mock_checker = MagicMock()
        mock_checker.get_pending_subjects.side_effect = lambda task, subjects: subjects
        mock_checker.is_group.return_value = False
        mock_checker.warn_missing_configs.return_value = []

        kwargs = dict(
            requested_tasks=["rest_preprocess"],
            input_dir="/input",
            output_dir="/output",
            work_dir="/work",
            container_dir="/containers",
            dry_run=False,
            context={"subjects": ["001"]},
            option_env={"session": "01"},
            project_config=MOCK_PROJECT_CONFIG,
            resume=True,
            checks_config_path="fake_checks.yaml",
        )
        kwargs.update(overrides)

        with patch(CONFIG_PATH, MOCK_CONFIG), \
             patch.object(executor, "_execute_single_task",
                          MagicMock(side_effect=lambda node, **kw: [f"job_{node.name}"])), \
             patch("neuromaestro.pipeline.dag.OutputChecker",
                   return_value=mock_checker) as mock_cls:
            executor.execute(**kwargs)

        return mock_cls

    def test_checker_is_built_from_output_dir(self):
        mock_cls = self._execute_with()
        assert mock_cls.call_args.kwargs["work_dir"] == "/output"

    def test_checker_does_not_use_the_work_dir(self):
        """The two are different roots in every documented invocation."""
        mock_cls = self._execute_with()
        assert mock_cls.call_args.kwargs["work_dir"] != "/work"

    def test_output_dir_is_followed_when_it_changes(self):
        mock_cls = self._execute_with(output_dir="/elsewhere/derivatives")
        assert mock_cls.call_args.kwargs["work_dir"] == "/elsewhere/derivatives"


class TestCheckerSettingsAndMessages:

    SUBJECTS = ["001", "002"]

    def _execute(self, completed=(), fail_on=None, resume=True, checks="checks.yaml",
                 tasks=("rest_preprocess",)):
        executor = make_executor()

        def fake_task(node, **kwargs):
            if node.name == fail_on:
                raise RuntimeError("sbatch: error")
            return [f"job_{node.name}"]

        checker = MagicMock()
        checker.is_group.return_value = False
        checker.get_pending_subjects.side_effect = lambda task, subjects: [s for s in subjects if s not in completed]
        with patch(CONFIG_PATH, MOCK_CONFIG), \
             patch.object(executor, "_execute_single_task", MagicMock(side_effect=fake_task)), \
             patch("neuromaestro.pipeline.dag.OutputChecker", return_value=checker) as checker_cls:
            executor.execute(
                requested_tasks=list(tasks), input_dir="/in", output_dir="/out", work_dir="/work",
                container_dir="/c", dry_run=False, context={"subjects": self.SUBJECTS},
                option_env={"session": "02"}, project_config={**MOCK_PROJECT_CONFIG, "prefix": "P"},
                resume=resume, checks_config_path=checks,
            )
        return checker_cls, checker

    def test_checker_uses_the_projects_prefix_and_the_run_session(self):
        checker_cls, checker = self._execute()
        checker_cls.assert_called_once_with(config_path="checks.yaml", work_dir="/out", prefix="P", session="02")
        checker.warn_missing_configs.assert_called_once_with(["rest_preprocess"])

    def test_resume_without_a_checks_config_checks_nothing(self):
        # run() passes resume=True with no path when the checks file is missing
        checker_cls, _ = self._execute(checks=None)
        checker_cls.assert_not_called()

    def test_skipped_subjects_are_named(self, capsys):
        self._execute(completed=("001",))
        assert "[resume] rest_preprocess: skipping 1 completed subject(s): 001" in capsys.readouterr().out.splitlines()

    def test_nothing_is_reported_when_nothing_was_skipped(self, capsys):
        self._execute()
        assert not any(line.startswith("[resume]") for line in capsys.readouterr().out.splitlines())

    def test_failure_after_a_submission_names_the_queued_jobs(self, capsys):
        with pytest.raises(RuntimeError, match="sbatch: error"):
            self._execute(resume=False, tasks=("rest_preprocess", "rest_post"), fail_on="rest_post")
        err = capsys.readouterr().err
        assert "Already submitted before this failure: job_rest_preprocess" in err
        assert "These jobs stay queued; cancel them if the partial run is unwanted." in err

    def test_failure_before_any_submission_mentions_no_queued_jobs(self, capsys):
        with pytest.raises(RuntimeError):
            self._execute(resume=False, fail_on="rest_preprocess")
        assert "Already submitted" not in capsys.readouterr().err
